import streamlit as st
import pandas as pd
import os
from datetime import datetime
from io import BytesIO
import base64
import requests

# Imports para PDF (reportlab)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# -----------------------------------
# CONFIGURAÇÃO INICIAL
# -----------------------------------
st.set_page_config(page_title="Sistema Estúdio de Pilates", layout="wide")

DATA_DIR = "data"
IMAGENS_DIR = "imagens"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGENS_DIR, exist_ok=True)

AVALIACOES_PATH = os.path.join(DATA_DIR, "avaliacoes.csv")
IMAGENS_CSV_PATH = os.path.join(DATA_DIR, "imagens.csv")
AGENDA_PATH = os.path.join(DATA_DIR, "agenda.csv")

# -----------------------------------
# AUTENTICAÇÃO DO SISTEMA
# -----------------------------------
st.title("Sistema Estúdio de Pilates")

senha = st.text_input("Digite a chave de acesso:", type="password")

if senha != "sistema.estudio.fernandapeixoto":
    st.warning("Acesso restrito. Insira a chave correta para continuar.")
    st.stop()

# -----------------------------------
# FUNÇÃO PARA NORMALIZAR HORÁRIO
# -----------------------------------
def normalizar_horario(h):
    """
    Recebe: 8, 8h, 8h0, 8h00, 8:0, 8:00, 08:00
    Retorna:
        horario_sort: 'HH:MM' (para ordenação)
        horario_display: 'HHhMM' (para exibir)
    """
    if not isinstance(h, str):
        return None, None

    h = h.lower().strip().replace(" ", "")
    h = h.replace("h", ":")

    if ":" not in h:
        h = h + ":00"

    if h.endswith(":"):
        h = h + "00"

    partes = h.split(":")
    if len(partes) != 2:
        return None, None

    hh, mm = partes

    if not hh.isdigit():
        return None, None
    if not mm.isdigit():
        mm = "00"

    hh = hh.zfill(2)
    mm = mm.zfill(2)

    horario_sort = f"{hh}:{mm}"
    horario_display = f"{hh}h{mm}"

    return horario_sort, horario_display

# -----------------------------------
# FUNÇÕES AUXILIARES CSV
# -----------------------------------
def load_csv(path, cols=None):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols if cols else [])

    df = pd.read_csv(path, dtype=str)  # força texto

    if cols:
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols]

    return df

# -----------------------------------
# INTEGRAÇÃO COM GITHUB
# -----------------------------------
def get_github_config():
    token = st.secrets["GITHUB_TOKEN"]
    repo = st.secrets["GITHUB_REPO"]
    branch = st.secrets.get("GITHUB_BRANCH", "main")
    base_api = f"https://api.github.com/repos/{repo}/contents"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }
    return base_api, headers, branch

def github_get_file_sha(path_in_repo):
    try:
        base_api, headers, branch = get_github_config()
    except Exception:
        return None

    url = f"{base_api}/{path_in_repo}"
    params = {"ref": branch}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 200:
        return r.json().get("sha")
    return None

def github_upload_file(local_path, path_in_repo, message):
    if not os.path.exists(local_path):
        return

    try:
        base_api, headers, branch = get_github_config()
    except Exception:
        return

    url = f"{base_api}/{path_in_repo}"

    with open(local_path, "rb") as f:
        content = f.read()

    content_b64 = base64.b64encode(content).decode("utf-8")
    sha = github_get_file_sha(path_in_repo)

    data = {
        "message": message,
        "content": content_b64,
        "branch": branch
    }
    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=headers, json=data)
    if r.status_code not in (200, 201):
        st.warning(f"Falha ao enviar {path_in_repo} para o GitHub: {r.status_code}")

def save_csv(df, path):
    df.to_csv(path, index=False)

    # Enviar CSV para o GitHub
    try:
        nome_arquivo = os.path.basename(path)
        github_upload_file(
            local_path=path,
            path_in_repo=f"data/{nome_arquivo}",
            message=f"Atualiza {nome_arquivo} via Streamlit"
        )
    except Exception as e:
        st.warning(f"Não foi possível sincronizar {path} com o GitHub: {e}")

def add_row(path, row_dict, cols=None):
    df = load_csv(path, cols=cols if cols else list(row_dict.keys()))
    df = pd.concat([df, pd.DataFrame([row_dict])], ignore_index=True)
    save_csv(df, path)

def fix_ids(df, id_col="id"):
    if id_col not in df.columns:
        df[id_col] = None

    df[id_col] = pd.to_numeric(df[id_col], errors="coerce")

    if df[id_col].isna().any() or df[id_col].duplicated().any():
        df = df.reset_index(drop=True)
        df[id_col] = range(1, len(df) + 1)

    return df

# -----------------------------------
# LIMPEZA COMPLETA DO AGENDA.CSV
# -----------------------------------
def limpar_agenda(df):
    if df.empty:
        return df

    df = df.dropna(how="all")
    df = df.drop_duplicates()

    if "horario" not in df.columns:
        df["horario"] = None

    df["horario"] = df["horario"].fillna("").astype(str)
    df = df[df["horario"].str.strip() != ""]

    return df.reset_index(drop=True)

# -----------------------------------
# CORRIGIR HORÁRIOS ANTIGOS
# -----------------------------------
def corrigir_horarios_antigos(df):
    if df.empty:
        return df

    if "horario" not in df.columns:
        df["horario"] = None
    if "horario_sort" not in df.columns:
        df["horario_sort"] = None

    for idx, row in df.iterrows():
        h_display = row.get("horario")

        if not isinstance(h_display, str):
            continue

        h_display = h_display.strip()

        # Se veio como "1900-01-01 08h00"
        if " " in h_display:
            h_display = h_display.split(" ")[-1]

        h_sort, h_disp = normalizar_horario(h_display)

        if not h_sort:
            continue

        df.at[idx, "horario_sort"] = h_sort
        df.at[idx, "horario"] = h_disp

    return df

# -----------------------------------
# FUNÇÃO PARA GERAR PDF DA AGENDA
# -----------------------------------
def gerar_pdf_agenda(agenda_df):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )

    elements = []
    styles = getSampleStyleSheet()
    estilo_titulo = styles["Heading1"]
    estilo_titulo.alignment = 1

    titulo = Paragraph("Agenda Semanal - Estúdio de Pilates", estilo_titulo)
    elements.append(titulo)
    elements.append(Spacer(1, 12))

    if agenda_df.empty:
        elements.append(Paragraph("Nenhum horário cadastrado."))
        doc.build(elements)
        return buffer.getvalue()

    dias_ordem = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
    cabecalhos = [d.capitalize() for d in dias_ordem]

    dados_por_dia = {}
    for dia in dias_ordem:
        dia_df = agenda_df[agenda_df["dia"] == dia].sort_values("horario_sort")
        linhas = []
        for _, row in dia_df.iterrows():
            linhas.append(
                f"{row['horario']} - {row['nome']} ({row['profissional']}) [{row['duracao']} min]"
            )
        if not linhas:
            linhas.append(" ")
        dados_por_dia[dia] = linhas

    max_linhas = max(len(dados_por_dia[d]) for d in dias_ordem)

    tabela_dados = [cabecalhos]

    for i in range(max_linhas):
        linha = []
        for dia in dias_ordem:
            lista = dados_por_dia[dia]
            linha.append(lista[i] if i < len(lista) else " ")
        tabela_dados.append(linha)

    tabela = Table(tabela_dados, repeatRows=1)

    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
    ]))

    elements.append(tabela)
    doc.build(elements)

    return buffer.getvalue()

# -----------------------------------
# LAYOUT PRINCIPAL
# -----------------------------------
aba_avaliacoes, aba_agenda, aba_comparacao = st.tabs([
    "Avaliações Posturais",
    "Agenda",
    "Comparar Avaliações"
])

# =====================================================================
# AVALIAÇÕES POSTURAIS
# =====================================================================
with aba_avaliacoes:
    st.header("Registro de Avaliações Posturais")

    aval_df = load_csv(AVALIACOES_PATH, cols=["id", "nome", "data"])
    aval_df = fix_ids(aval_df)
    save_csv(aval_df, AVALIACOES_PATH)

    img_df = load_csv(IMAGENS_CSV_PATH, cols=["avaliacao_id", "arquivo", "data"])

    st.subheader("Filtrar avaliações")
    filtro = st.text_input("Digite parte do nome para filtrar")

    aval_filtradas = (
        aval_df[aval_df["nome"].str.contains(filtro, case=False, na=False)]
        if filtro.strip() else aval_df
    )

    st.markdown("---")

    st.subheader("Criar nova avaliação")

    nome = st.text_input("Nome da pessoa avaliada")
    data_av = st.date_input("Data da avaliação")

    uploaded = st.file_uploader(
        "Fotos da avaliação", type=["png", "jpg", "jpeg"], accept_multiple_files=True
    )

    if st.button("Salvar avaliação"):
        if nome.strip() == "":
            st.error("O nome é obrigatório.")
        else:
            novo_id = 1 if aval_df.empty else int(aval_df["id"].max()) + 1

            add_row(AVALIACOES_PATH, {
                "id": novo_id,
                "nome": nome,
                "data": data_av
            })

            if uploaded:
                for file in uploaded:
                    file_name = f"{novo_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.name}"
                    file_path = os.path.join(IMAGENS_DIR, file_name)
                    with open(file_path, "wb") as f:
                        f.write(file.getbuffer())

                    # salvar no CSV de imagens
                    add_row(IMAGENS_CSV_PATH, {
                        "avaliacao_id": novo_id,
                        "arquivo": file_name,
                        "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

                    # enviar imagem para o GitHub
                    try:
                        github_upload_file(
                            local_path=file_path,
                            path_in_repo=f"imagens/{file_name}",
                            message=f"Adiciona imagem {file_name} via Streamlit"
                        )
                    except Exception as e:
                        st.warning(f"Não foi possível enviar a imagem {file_name} para o GitHub: {e}")

            st.success("Avaliação registrada com sucesso.")
            st.rerun()

    st.markdown("---")
    st.subheader("Avaliações registradas")

    if aval_filtradas.empty:
        st.info("Nenhuma avaliação encontrada.")
    else:
        for _, row in aval_filtradas.sort_values("data", ascending=False).iterrows():
            st.markdown(f"### {row['nome']} — {row['data']}")

            fotos = img_df[img_df["avaliacao_id"] == row["id"]]

            texto_export = (
                f"Avaliação Postural\n"
                f"Nome: {row['nome']}\n"
                f"Data: {row['data']}\n"
                f"Fotos: {len(fotos)} imagens\n"
            )

            st.download_button(
                "Baixar avaliação (.txt)",
                texto_export,
                file_name=f"avaliacao_{row['id']}.txt"
            )

            if st.button("Excluir avaliação", key=f"del_av_{row['id']}"):
                for _, frow in fotos.iterrows():
                    img_path = os.path.join(IMAGENS_DIR, frow["arquivo"])
                    if os.path.exists(img_path):
                        os.remove(img_path)

                img_df = img_df[img_df["avaliacao_id"] != row["id"]]
                save_csv(img_df, IMAGENS_CSV_PATH)

                aval_df = aval_df[aval_df["id"] != row["id"]]
                save_csv(aval_df, AVALIACOES_PATH)

                st.success("Avaliação removida.")
                st.rerun()

            if fotos.empty:
                st.write("Sem fotos registradas.")
            else:
                cols = st.columns(3)
                for idx, (_, frow) in enumerate(fotos.iterrows()):
                    with cols[idx % 3]:
                        img_path = os.path.join(IMAGENS_DIR, frow["arquivo"])
                        if os.path.exists(img_path):
                            st.image(img_path, caption=frow["data"])

            st.markdown("---")

# =====================================================================
# AGENDA
# =====================================================================
with aba_agenda:
    st.header("Agenda da Semana")

    agenda_df = load_csv(
        AGENDA_PATH,
        cols=["id", "dia", "horario", "horario_sort", "nome", "profissional", "duracao"]
    )

    agenda_df = limpar_agenda(agenda_df)
    agenda_df = corrigir_horarios_antigos(agenda_df)

    agenda_df["horario_sort"] = pd.to_datetime(
        agenda_df["horario_sort"], format="%H:%M", errors="coerce"
    )

    agenda_df = agenda_df.dropna(subset=["horario_sort"])
    agenda_df = fix_ids(agenda_df)

    save_csv(agenda_df, AGENDA_PATH)

    st.subheader("Exportação da agenda")
    if st.button("Gerar PDF da agenda semanal"):
        pdf_bytes = gerar_pdf_agenda(agenda_df)
        st.download_button(
            label="Baixar agenda semanal em PDF",
            data=pdf_bytes,
            file_name="agenda_semanal.pdf",
            mime="application/pdf"
        )

    st.markdown("---")
    st.subheader("Gerenciamento da agenda")

    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
    col_dias = st.columns(len(dias))

    for i, dia in enumerate(dias):
        with col_dias[i]:
            st.subheader(dia.capitalize())

            dia_df = agenda_df[agenda_df["dia"] == dia].sort_values("horario_sort")

            for _, row in dia_df.iterrows():
                st.markdown(f"**{row['horario']}** — {row['nome']} ({row['profissional']})")
                st.caption(f"{row['duracao']} min")

                if st.button("Excluir", key=f"del_{row['id']}"):
                    agenda_df = agenda_df[agenda_df["id"] != row["id"]]
                    save_csv(agenda_df, AGENDA_PATH)
                    st.rerun()

                st.markdown("---")

            st.markdown("**Novo horário**")
            horario_raw = st.text_input(f"Horário ({dia})", key=f"hora_{dia}")
            nome = st.text_input("Nome", key=f"nome_{dia}")
            profissional = st.text_input("Profissional", key=f"prof_{dia}")

            duracao = st.number_input(
                "Duração (min)",
                min_value=10,
                max_value=180,
                step=5,
                value=45,
                key=f"dur_{dia}"
            )

            if st.button(f"Adicionar {dia}", key=f"add_{dia}"):
                horario_sort, horario_display = normalizar_horario(horario_raw)

                if not horario_sort:
                    st.error("Horário inválido. Exemplos válidos: 8, 8h, 8h00, 08:00")
                elif nome.strip() == "" or profissional.strip() == "":
                    st.error("Preencha horário, nome e profissional.")
                else:
                    novo_id = 1 if agenda_df.empty else int(agenda_df["id"].max()) + 1

                    add_row(AGENDA_PATH, {
                        "id": novo_id,
                        "dia": dia,
                        "horario": horario_display,
                        "horario_sort": horario_sort,
                        "nome": nome,
                        "profissional": profissional,
                        "duracao": duracao
                    })

                    st.success("Horário adicionado.")
                    st.rerun()

# =====================================================================
# COMPARAÇÃO ENTRE AVALIAÇÕES
# =====================================================================
with aba_comparacao:
    st.header("Comparar Avaliações Posturais")

    aval_df = load_csv(AVALIACOES_PATH, cols=["id", "nome", "data"])
    img_df = load_csv(IMAGENS_CSV_PATH, cols=["avaliacao_id", "arquivo", "data"])

    if aval_df.empty:
        st.info("Nenhuma avaliação registrada ainda.")
    else:
        col1, col2 = st.columns(2)

        with col1:
            id1 = st.selectbox(
                "Selecione a primeira avaliação",
                aval_df["id"].tolist(),
                format_func=lambda x: f"{aval_df.loc[aval_df['id']==x,'nome'].values[0]} — {aval_df.loc[aval_df['id']==x,'data'].values[0]}"
            )

        with col2:
            id2 = st.selectbox(
                "Selecione a segunda avaliação",
                aval_df["id"].tolist(),
                format_func=lambda x: f"{aval_df.loc[aval_df['id']==x,'nome'].values[0]} — {aval_df.loc[aval_df['id']==x,'data'].values[0]}"
            )

        st.markdown("## Comparação lado a lado")

        fotos1 = img_df[img_df["avaliacao_id"] == id1]
        fotos2 = img_df[img_df["avaliacao_id"] == id2]

        colA, colB = st.columns(2)

        with colA:
            st.subheader("Avaliação 1")
            for _, row in fotos1.iterrows():
                img_path = os.path.join(IMAGENS_DIR, row["arquivo"])
                if os.path.exists(img_path):
                    st.image(img_path, caption=row["data"])

        with colB:
            st.subheader("Avaliação 2")
            for _, row in fotos2.iterrows():
                img_path = os.path.join(IMAGENS_DIR, row["arquivo"])
                if os.path.exists(img_path):
                    st.image(img_path, caption=row["data"])

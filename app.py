import streamlit as st
import pandas as pd
import requests
from datetime import date

st.set_page_config(page_title="電子データ購入管理", layout="wide")
st.title("📚 電子データ購入管理")

COLUMNS = [
    "固有ID",
    "タイトル",
    "種別",
    "作者・サークル",
    "CV・出演者",
    "購入元",
    "購入日",
    "備考"
]

# StreamlitのSecretsからGASのURLを取得
GAS_URL = st.secrets.get("GAS_URL", "")

if not GAS_URL:
    st.warning("Streamlitの「Settings」→「Secrets」に GAS_URL を設定してください。")
    st.code('GAS_URL = "ここにコピーしたウェブアプリのURLを貼り付け"', language="toml")
    st.stop()

@st.cache_data(ttl=60)
def load_data():
    try:
        res = requests.get(GAS_URL, timeout=15)
        res.raise_for_status()
        data = res.json()
        df = pd.DataFrame(data, columns=COLUMNS)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[COLUMNS].fillna("").astype(str)
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        return pd.DataFrame(columns=COLUMNS)

def add_row(row_dict):
    res = requests.post(GAS_URL, json=row_dict, timeout=15)
    res.raise_for_status()
    return res.json()

def check_duplicates(df, item_id, title):
    warnings = []
    if item_id:
        id_clean = item_id.strip().upper()
        id_match = df[df["固有ID"].str.strip().str.upper() == id_clean]
        if not id_match.empty:
            matched_title = id_match.iloc[0]["タイトル"]
            warnings.append(f"【ID重複】同じ固有ID（{item_id}）が既に登録されています: 『{matched_title}』")

    if title:
        title_clean = title.strip()
        title_matches = df[df["タイトル"].str.contains(title_clean, case=False, na=False, regex=False)]
        for _, row in title_matches.iterrows():
            if not item_id or row["固有ID"].strip().upper() != item_id.strip().upper():
                warnings.append(f"【タイトル類似】似たタイトルの作品があります: 『{row['タイトル']}』（ID: {row['固有ID'] or '未設定'}）")
    return warnings

df = load_data()

tab1, tab2 = st.tabs(["🔍 登録一覧・検索", "➕ 新規登録"])

with tab1:
    col_top1, col_top2 = st.columns([4, 1])
    with col_top1:
        st.subheader("登録済みデータの検索")
    with col_top2:
        if st.button("🔄 最新データに更新"):
            st.cache_data.clear()
            st.rerun()

    col_s, col_f1, col_f2 = st.columns([2, 1, 1])
    with col_s:
        keyword = st.text_input("キーワード検索", placeholder="タイトル・サークル・CV・IDで検索")
    with col_f1:
        type_list = ["すべて"] + sorted([x for x in df["種別"].unique() if x])
        type_filter = st.selectbox("種別で絞り込み", type_list)
    with col_f2:
        plat_list = ["すべて"] + sorted([x for x in df["購入元"].unique() if x])
        platform_filter = st.selectbox("購入元で絞り込み", plat_list)

    filtered_df = df.copy()
    if keyword:
        mask = (
            filtered_df["タイトル"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["固有ID"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["作者・サークル"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["CV・出演者"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["備考"].str.contains(keyword, case=False, na=False, regex=False)
        )
        filtered_df = filtered_df[mask]

    if type_filter != "すべて":
        filtered_df = filtered_df[filtered_df["種別"] == type_filter]

    if platform_filter != "すべて":
        filtered_df = filtered_df[filtered_df["購入元"] == platform_filter]

    st.write(f"表示件数: **{len(filtered_df)}** 件 / 全 **{len(df)}** 件")
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("作品の新規登録")
    with st.form("register_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            media_type = st.selectbox("種別", ["ボイス/ASMR", "漫画", "小説", "ゲーム", "その他"])
            item_id = st.text_input("固有ID（RJ番号 / ISBN / ASIN）", placeholder="例: RJ123456")
            title = st.text_input("タイトル *", placeholder="作品名を入力")
            creator = st.text_input("作者・サークル名")
        with col2:
            cv = st.text_input("CV・出演者", placeholder="声優名など（複数可）")
            platform = st.selectbox("購入元", ["DLsite", "Amazon", "FANZA", "DMM", "BOOTH", "その他"])
            purchase_date = st.date_input("購入日", value=date.today())
            note = st.text_input("備考", placeholder="セール情報やメモなど")

        force_submit = st.checkbox("重複警告を無視して強制登録する")
        submitted = st.form_submit_button("登録する")

    if submitted:
        if not title.strip():
            st.error("タイトルは必須項目です。")
        else:
            dup_warnings = check_duplicates(df, item_id, title)
            if dup_warnings and not force_submit:
                st.warning("⚠️ 重複の可能性があります！")
                for w in dup_warnings:
                    st.write(f"- {w}")
                st.info("別バージョン等で登録したい場合は「重複警告を無視して強制登録する」にチェックを入れて再度「登録する」を押してください。")
            else:
                new_row = {
                    "固有ID": item_id.strip(),
                    "タイトル": title.strip(),
                    "種別": media_type,
                    "作者・サークル": creator.strip(),
                    "CV・出演者": cv.strip(),
                    "購入元": platform,
                    "購入日": purchase_date.strftime("%Y/%m/%d"),
                    "備考": note.strip()
                }
                with st.spinner("スプレッドシートに保存中..."):
                    try:
                        res_json = add_row(new_row)
                        if res_json.get("status") == "success":
                            st.success(f"『{title}』をスプレッドシートに登録しました！")
                            st.cache_data.clear()
                        else:
                            st.error(f"保存エラー: {res_json}")
                    except Exception as e:
                        st.error(f"通信エラーが発生しました: {e}")

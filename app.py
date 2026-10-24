import streamlit as st
import pandas as pd
import requests
import re
import html
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

def fetch_dlsite_info(rj_id):
    """RJ/BJ/VJ番号からDLsiteの公開APIを使って作品情報を自動取得する"""
    rj_id = rj_id.strip().upper()
    for site in ["maniax", "home", "books", "girls", "pro"]:
        api_url = f"https://www.dlsite.com/{site}/api/=/product.json?workno={rj_id}&locale=ja_JP"
        try:
            res = requests.get(api_url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0 and data[0].get("work_name"):
                    item = data[0]
                    title = html.unescape(str(item.get("work_name", "")))
                    maker = html.unescape(str(item.get("maker_name", "")))

                    cvs = []
                    authors = []
                    creaters = item.get("creaters", {})
                    if isinstance(creaters, dict):
                        for v in creaters.get("voice_by", []):
                            if isinstance(v, dict) and v.get("name"):
                                cvs.append(v["name"])
                        for a in creaters.get("author", []):
                            if isinstance(a, dict) and a.get("name"):
                                authors.append(a["name"])
                    elif isinstance(creaters, list):
                        for c_group in creaters:
                            if isinstance(c_group, dict):
                                for v in c_group.get("voice_by", []):
                                    if isinstance(v, dict) and v.get("name"):
                                        cvs.append(v["name"])

                    wtype = str(item.get("work_type", ""))
                    wtype_str = str(item.get("work_type_string", ""))
                    if wtype in ["SOU", "ASM", "MUS"] or "ボイス" in wtype_str or "ASMR" in wtype_str or "音" in wtype_str:
                        media_type = "ボイス/ASMR"
                    elif wtype in ["MNG", "COM", "SCM"] or "マンガ" in wtype_str or "劇画" in wtype_str or "CG" in wtype_str:
                        media_type = "漫画"
                    elif wtype in ["NRE", "NOV"] or "ノベル" in wtype_str or "小説" in wtype_str:
                        media_type = "小説"
                    elif wtype in ["ACN", "RPG", "ADV", "SLG", "STG", "PZL", "QIZ", "TBL", "DNV"]:
                        media_type = "ゲーム"
                    else:
                        media_type = "ボイス/ASMR" if cvs else "その他"

                    creator_str = maker
                    if authors and not maker:
                        creator_str = " / ".join(authors)

                    return {
                        "固有ID": rj_id,
                        "タイトル": title,
                        "種別": media_type,
                        "作者・サークル": creator_str,
                        "CV・出演者": " / ".join(cvs),
                        "購入元": "DLsite",
                        "購入日": date.today().strftime("%Y/%m/%d"),
                        "備考": ""
                    }
        except Exception:
            continue
    return {
        "固有ID": rj_id,
        "タイトル": "（自動取得失敗：手動で入力してください）",
        "種別": "ボイス/ASMR",
        "作者・サークル": "",
        "CV・出演者": "",
        "購入元": "DLsite",
        "購入日": date.today().strftime("%Y/%m/%d"),
        "備考": ""
    }

df = load_data()

tab1, tab2, tab3 = st.tabs(["🔍 登録一覧・検索", "➕ 1件登録", "📦 まとめて一括登録"])

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
    st.subheader("作品の1件登録")
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

with tab3:
    st.subheader("📦 まとめて一括登録")
    st.caption("DLsiteの購入履歴やRJ番号、またはAmazon等のタイトル一覧からまとめてデータを読み込んで一括登録できます。")

    if "bulk_df" not in st.session_state:
        st.session_state.bulk_df = pd.DataFrame(columns=COLUMNS)

    sub_a, sub_b = st.tabs(["🎧 方法A：DLsite（RJ番号・購入履歴）から自動取得", "📖 方法B：タイトル一覧テキストから一括作成"])

    with sub_a:
        rj_text = st.text_area(
            "RJ/BJ/VJ番号、またはDLsiteの購入履歴ページのテキストをそのまま貼り付け",
            placeholder="例:\nRJ123456\nRJ234567\n（※DLsiteの購入履歴画面を丸ごとコピー＆ペーストしても自動でRJ番号だけ抽出します）",
            height=130
        )
        col_d1, col_d2 = st.columns([1, 2])
        with col_d1:
            dlsite_date = st.date_input("一括設定する購入日", value=date.today(), key="dl_date")
        if st.button("① DLsiteから作品情報をまとめて取得"):
            codes = list(dict.fromkeys(re.findall(r"[RVB]J\d{6,8}", rj_text.upper())))
            if not codes:
                st.warning("テキスト内にRJ/BJ/VJ番号が見つかりませんでした。")
            else:
                existing_ids = set(df["固有ID"].str.strip().str.upper())
                new_rows = []
                skipped = []
                prog = st.progress(0, text="DLsiteから作品情報を取得中...")
                for i, code in enumerate(codes):
                    if code in existing_ids:
                        skipped.append(code)
                    else:
                        info = fetch_dlsite_info(code)
                        info["購入日"] = dlsite_date.strftime("%Y/%m/%d")
                        new_rows.append(info)
                    prog.progress((i + 1) / len(codes), text=f"取得中 ({i + 1}/{len(codes)}): {code}")
                prog.empty()
                if skipped:
                    st.info(f"既に登録済みのID（{len(skipped)}件）は自動で除外しました: {', '.join(skipped)}")
                if new_rows:
                    st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(new_rows)], ignore_index=True)
                    st.success(f"{len(new_rows)}件の作品情報を下のプレビュー表に追加しました！内容を確認して「② 一括登録する」を押してください。")

    with sub_b:
        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            bulk_type = st.selectbox("一括設定する種別", ["漫画", "小説", "ボイス/ASMR", "ゲーム", "その他"], key="b_type")
        with col_b2:
            bulk_plat = st.selectbox("一括設定する購入元", ["Amazon", "DLsite", "DMM", "FANZA", "BOOTH", "その他"], key="b_plat")
        with col_b3:
            bulk_date = st.date_input("一括設定する購入日", value=date.today(), key="b_date")

        lines_text = st.text_area(
            "1行に1作品のタイトルを入力（『タイトル, 作者名』のようにカンマやタブで区切ると作者も同時に入ります）",
            placeholder="例:\n〇〇の冒険 第1巻, 山田太郎\n〇〇の冒険 第2巻, 山田太郎",
            height=130
        )
        if st.button("① 下のプレビュー表に追加"):
            lines = [line.strip() for line in lines_text.splitlines() if line.strip()]
            if not lines:
                st.warning("テキストを入力してください。")
            else:
                added_rows = []
                for line in lines:
                    parts = re.split(r"[\t,、]", line, maxsplit=1)
                    t_val = parts[0].strip()
                    c_val = parts[1].strip() if len(parts) > 1 else ""
                    added_rows.append({
                        "固有ID": "",
                        "タイトル": t_val,
                        "種別": bulk_type,
                        "作者・サークル": c_val,
                        "CV・出演者": "",
                        "購入元": bulk_plat,
                        "購入日": bulk_date.strftime("%Y/%m/%d"),
                        "備考": ""
                    })
                st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(added_rows)], ignore_index=True)
                st.success(f"{len(added_rows)}件を下のプレビュー表に追加しました！")

    st.subheader("登録前の確認・編集プレビュー表")
    st.caption("表のセルをダブルクリックして直接文字を修正したり、末尾の「＋」で行を追加できます。")
    edited_df = st.data_editor(
        st.session_state.bulk_df,
        num_rows="dynamic",
        use_container_width=True,
        key="bulk_editor"
    )

    col_act1, col_act2 = st.columns([2, 1])
    with col_act1:
        if st.button("🚀 ② プレビュー表の内容をスプレッドシートに一括登録する", type="primary"):
            valid_rows = [row for _, row in edited_df.iterrows() if str(row.get("タイトル", "")).strip()]
            if not valid_rows:
                st.warning("登録するデータがありません。上のフォームから追加するか、表に直接入力してください。")
            else:
                prog_save = st.progress(0, text="スプレッドシートへ順番に保存中...")
                success_count = 0
                for idx, row in enumerate(valid_rows):
                    row_dict = {col: str(row.get(col, "")).strip() for col in COLUMNS}
                    try:
                        res_json = add_row(row_dict)
                        if res_json.get("status") == "success":
                            success_count += 1
                    except Exception as e:
                        st.error(f"『{row_dict.get('タイトル')}』の保存時にエラーが発生しました: {e}")
                    prog_save.progress((idx + 1) / len(valid_rows), text=f"保存中 ({idx + 1}/{len(valid_rows)})")
                prog_save.empty()
                st.success(f"完了！ {success_count} 件の作品をスプレッドシートに一括登録しました！")
                st.session_state.bulk_df = pd.DataFrame(columns=COLUMNS)
                st.cache_data.clear()
    with col_act2:
        if st.button("🗑️ プレビュー表を空にする"):
            st.session_state.bulk_df = pd.DataFrame(columns=COLUMNS)
            st.rerun()

import streamlit as st
import pandas as pd
import requests
import re
import html
from datetime import date
from collections import Counter

st.set_page_config(page_title="電子データ購入管理", layout="wide")
st.title("📚 電子データ購入管理")

COLUMNS = [
    "固有ID",
    "タイトル",
    "種別",
    "版・仕様",
    "所持巻数",
    "完結",
    "作者・サークル",
    "CV・出演者",
    "購入元",
    "購入日",
    "備考"
]

EDITION_OPTIONS = [
    "通常",
    "特装版・限定版",
    "フルカラー",
    "セミカラー",
    "文庫・新装版",
    "通常＋特装版（二重所持）",
    "通常＋フルカラー（二重所持）",
    "通常＋セミカラー（二重所持）",
    "別版・その他"
]

TYPE_COLOR_MAP = {
    "漫画": "background-color: #E8F0FE; color: #1F1F1F;",
    "小説": "background-color: #E6F4EA; color: #1F1F1F;",
    "ボイス/ASMR": "background-color: #FCE8E6; color: #1F1F1F;",
    "ゲーム": "background-color: #FEF7E0; color: #1F1F1F;",
}

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
        df = df[COLUMNS].fillna("").astype(str)
        df["版・仕様"] = df["版・仕様"].apply(lambda x: x if x.strip() else "通常")
        return df
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        return pd.DataFrame(columns=COLUMNS)

def add_row(row_dict):
    res = requests.post(GAS_URL, json=row_dict, timeout=15)
    res.raise_for_status()
    return res.json()

def normalize_base_title(title):
    t = str(title).strip()
    t = re.sub(r"[\[【\(（].*?(特装|限定|フルカラー|セミカラー|カラー|デジタル版|文庫|新装|愛蔵|完全版).*?[\]】\)）]", "", t)
    t = re.sub(r"\s*(特装版|限定版|フルカラー版?|セミカラー版?|文庫版|新装版|愛蔵版|完全版)$", "", t)
    return t.strip()

def parse_volume_tokens(vol_str):
    s = str(vol_str).strip()
    if not s:
        return [], []
    raw_tokens = [tok.strip() for tok in re.split(r"[,、\s/／]+", s) if tok.strip()]
    expanded = []
    multi_spec_vols = []

    for tok in raw_tokens:
        if re.search(r"(\+|＋|＆|&|両方|二重)", tok):
            m_num = re.match(r"^(\d+(?:\.\d+)?)", tok)
            v_label = m_num.group(1) if m_num else tok
            multi_spec_vols.append(f"{v_label}巻({tok})")
            expanded.append(v_label)
            continue

        m_range = re.match(r"^(\d+)\s*[〜~\-－]\s*(\d+)", tok)
        if m_range:
            start_v, end_v = int(m_range.group(1)), int(m_range.group(2))
            if start_v <= end_v and (end_v - start_v) <= 200:
                for v in range(start_v, end_v + 1):
                    expanded.append(str(v))
            else:
                expanded.append(tok)
            continue

        m_single = re.match(r"^(\d+(?:\.\d+)?)(.*)$", tok)
        if m_single:
            num_part = m_single.group(1)
            expanded.append(num_part)
            continue

        expanded.append(tok)

    counts = Counter(expanded)
    dup_vols = [v for v, c in counts.items() if c >= 2]
    for dv in dup_vols:
        multi_spec_vols.append(f"{dv}巻(複数所持)")

    return expanded, list(dict.fromkeys(multi_spec_vols))

def detect_all_dual_owned(df):
    base_titles = df["タイトル"].apply(normalize_base_title)
    title_counts = Counter([bt for bt in base_titles if bt])

    reasons_per_index = {}
    for idx, row in df.iterrows():
        reasons = []
        bt = normalize_base_title(row["タイトル"])
        ed = str(row["版・仕様"]).strip()
        vol_str = str(row["所持巻数"]).strip()

        if bt and title_counts[bt] >= 2:
            other_editions = df[base_titles == bt]["版・仕様"].tolist()
            reasons.append(f"別行で複数版登録あり（{' / '.join(other_editions)}）")

        if "＋" in ed or "+" in ed or "二重" in ed:
            reasons.append(f"仕様欄で二重所持（{ed}）")

        _, dup_vols = parse_volume_tokens(vol_str)
        if dup_vols:
            reasons.append(f"巻数重複・別仕様あり（{', '.join(dup_vols)}）")

        if reasons:
            reasons_per_index[idx] = " / ".join(reasons)
    return reasons_per_index

def check_duplicates(df, item_id, title, edition, volumes):
    warnings = []
    if item_id:
        id_clean = item_id.strip().upper()
        id_match = df[df["固有ID"].str.strip().str.upper() == id_clean]
        if not id_match.empty:
            matched_row = id_match.iloc[0]
            warnings.append(
                f"【ID完全一致】同じ固有ID（{item_id}）が既に登録されています: "
                f"『{matched_row['タイトル']}』（版: {matched_row['版・仕様']} / 巻: {matched_row['所持巻数'] or '未設定'}）"
            )

    if title:
        base_input = normalize_base_title(title)
        new_vols, _ = parse_volume_tokens(volumes)
        for _, row in df.iterrows():
            row_title = str(row["タイトル"]).strip()
            row_base = normalize_base_title(row_title)
            row_ed = str(row["版・仕様"]).strip()
            row_vols_str = str(row["所持巻数"]).strip()
            row_vols, _ = parse_volume_tokens(row_vols_str)

            if base_input and row_base and (base_input.lower() == row_base.lower() or base_input.lower() in row_base.lower() or row_base.lower() in base_input.lower()):
                overlap_vols = sorted(set(new_vols) & set(row_vols))
                if row_ed != edition:
                    warnings.append(
                        f"【別仕様の所持あり】『{row_title}』は既に **[{row_ed}]**（所持巻: {row_vols_str or '未設定'}）で登録されています。"
                        f"（今回: [{edition}] との二重所持になります）"
                    )
                elif overlap_vols:
                    warnings.append(
                        f"【同一巻の重複】『{row_title}』[{row_ed}] の **{', '.join(overlap_vols)}巻** は既に所持しています！"
                        f"（登録済み巻: {row_vols_str}）"
                    )
                else:
                    warnings.append(
                        f"【同一作品あり】『{row_title}』[{row_ed}] が登録されています（登録済み巻: {row_vols_str or '未設定'}）。"
                    )
    return warnings

def fetch_dlsite_info(rj_id):
    rj_id = rj_id.strip().upper()
    for site in ["maniax", "home", "books", "girls", "pro", "comic"]:
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

                    edition = "通常"
                    if "フルカラー" in title:
                        edition = "フルカラー"
                    elif "セミカラー" in title:
                        edition = "セミカラー"
                    elif "特装版" in title or "限定版" in title:
                        edition = "特装版・限定版"

                    creator_str = " / ".join(authors) if authors else maker

                    return {
                        "固有ID": rj_id,
                        "タイトル": title,
                        "種別": media_type,
                        "版・仕様": edition,
                        "所持巻数": "",
                        "完結": "",
                        "作者・サークル": creator_str,
                        "CV・出演者": " / ".join(cvs),
                        "購入元": "DLsite",
                        "購入日": date.today().strftime("%Y/%m/%d"),
                        "備考": maker if (authors and maker and maker not in authors) else ""
                    }
        except Exception:
            continue
    return {
        "固有ID": rj_id,
        "タイトル": "（自動取得失敗：手動で入力してください）",
        "種別": "ボイス/ASMR",
        "版・仕様": "通常",
        "所持巻数": "",
        "完結": "",
        "作者・サークル": "",
        "CV・出演者": "",
        "購入元": "DLsite",
        "購入日": date.today().strftime("%Y/%m/%d"),
        "備考": ""
    }

def compress_int_volumes(nums):
    if not nums:
        return ""
    nums = sorted(set(nums))
    ranges = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(f"{start}〜{prev}" if start != prev else f"{start}")
            start = prev = n
    ranges.append(f"{start}〜{prev}" if start != prev else f"{start}")
    return ", ".join(ranges)

def parse_dlsite_copied_text(text, fallback_date):
    """
    DLsiteの画面（購入履歴テーブル、DLsite Play本棚など）から丸ごとコピーしたテキストを
    自動判定・解析し、不要な表ヘッダーやボタン文字をカットしてシリーズごとに巻数を集約する
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    userbuy_date_pat = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}:\d{1,2}))?")
    play_date_pat = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s*購入")
    meta_pat = re.compile(r"^(?:(\d+)/(\d+)作品)?(マンガ・CG|ボイス・ASMR|ノベル|ゲーム|動画|音楽|ツール|その他)?$")

    raw_items = []

    # パターン1: 購入履歴テーブル（2026/08/24 02:01 形式の日付を含むテーブル）
    if any(userbuy_date_pat.match(l) for l in lines):
        i = 0
        while i < len(lines):
            line = lines[i]
            m_date = userbuy_date_pat.match(line)
            if m_date:
                d_str = f"{int(m_date.group(1)):04d}/{int(m_date.group(2)):02d}/{int(m_date.group(3)):02d}"
                if i + 1 < len(lines):
                    title = lines[i+1]
                    maker = ""
                    cat_str = ""
                    for j in range(i+2, min(i+6, len(lines))):
                        sub_l = lines[j]
                        if userbuy_date_pat.match(sub_l):
                            break
                        if any(k in sub_l for k in ["全年齢", "R-18", "マンガ", "ボイス", "ノベル", "ゲーム"]):
                            cat_str = sub_l
                        elif not maker and not any(k in sub_l for k in ["視聴", "評価", "ポイント", "円", "クレジット", "-"]):
                            maker = sub_l

                    mtype = "漫画"
                    if "ボイス" in cat_str or "ASMR" in cat_str or "音" in cat_str:
                        mtype = "ボイス/ASMR"
                    elif "ノベル" in cat_str or "小説" in cat_str:
                        mtype = "小説"
                    elif "ゲーム" in cat_str:
                        mtype = "ゲーム"

                    raw_items.append({
                        "title": title,
                        "maker": maker,
                        "mtype": mtype,
                        "date": d_str,
                        "owned_cnt": None,
                        "total_cnt": None
                    })
            i += 1

    # パターン2: DLsite Play本棚画面（2026年8月24日 購入 形式）
    elif any(play_date_pat.match(l) for l in lines):
        current_date = fallback_date
        buffer = []
        for line in lines:
            m_date = play_date_pat.match(line)
            if m_date:
                current_date = f"{int(m_date.group(1)):04d}/{int(m_date.group(2)):02d}/{int(m_date.group(3)):02d}"
                buffer = []
                continue

            m_meta = meta_pat.match(line)
            if m_meta and (m_meta.group(1) or m_meta.group(3)):
                owned_cnt = m_meta.group(1)
                total_cnt = m_meta.group(2)
                cat_str = m_meta.group(3) or ""
                if len(buffer) >= 2:
                    t_val = buffer[-2]
                    m_val = buffer[-1]
                elif len(buffer) == 1:
                    t_val = buffer[-1]
                    m_val = ""
                else:
                    continue

                if "ボイス" in cat_str or "ASMR" in cat_str or "音" in cat_str:
                    mtype = "ボイス/ASMR"
                elif "ノベル" in cat_str:
                    mtype = "小説"
                elif "ゲーム" in cat_str:
                    mtype = "ゲーム"
                else:
                    mtype = "漫画"

                raw_items.append({
                    "title": t_val,
                    "maker": m_val,
                    "mtype": mtype,
                    "date": current_date,
                    "owned_cnt": owned_cnt,
                    "total_cnt": total_cnt
                })
                buffer = []
            else:
                buffer.append(line)

    if not raw_items:
        return []

    # タイトル末尾の巻数（例: （４）, (3), 　８, 7巻 等）を自動抽出し、シリーズ単位でまとめる
    vol_suffix_pat = re.compile(r"^(.*?)(?:[\s　]*[第\(（【\[巻]*(\d+)[\)）】\]巻]*)$")
    grouped = {}
    order_keys = []

    for it in raw_items:
        t = it["title"].strip()
        t_norm = t.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        m_vol = vol_suffix_pat.match(t_norm)
        if m_vol and not it.get("owned_cnt") and m_vol.group(1).strip():
            base_t = m_vol.group(1).strip()
            v_num = int(m_vol.group(2))
            key = (base_t, it["maker"], it["mtype"])
            if key not in grouped:
                grouped[key] = {"vols": [], "date": it["date"], "owned_cnt": None, "total_cnt": None}
                order_keys.append(key)
            grouped[key]["vols"].append(v_num)
        else:
            key = (t, it["maker"], it["mtype"], len(order_keys))
            grouped[key] = {
                "vols": [],
                "date": it["date"],
                "owned_cnt": it.get("owned_cnt"),
                "total_cnt": it.get("total_cnt"),
                "exact_title": t
            }
            order_keys.append(key)

    final_rows = []
    for key in order_keys:
        g = grouped[key]
        title_out = g.get("exact_title", key[0])
        maker_out = key[1]
        mtype_out = key[2]

        if g["vols"]:
            vol_str = compress_int_volumes(g["vols"])
            note_str = ""
        elif g.get("owned_cnt"):
            vol_str = f"計{g['owned_cnt']}冊（巻数未展開）"
            note_str = f"DLsite Play集約表示({g['owned_cnt']}/{g['total_cnt']})"
        else:
            vol_str = ""
            note_str = ""

        edition = "通常"
        if "フルカラー" in title_out:
            edition = "フルカラー"
        elif "セミカラー" in title_out:
            edition = "セミカラー"
        elif "特装版" in title_out or "限定版" in title_out:
            edition = "特装版・限定版"

        final_rows.append({
            "固有ID": "",
            "タイトル": title_out,
            "種別": mtype_out,
            "版・仕様": edition,
            "所持巻数": vol_str,
            "完結": "",
            "作者・サークル": maker_out,
            "CV・出演者": "",
            "購入元": "DLsite",
            "購入日": g["date"],
            "備考": note_str
        })
    return final_rows

def style_by_type(df_to_style):
    def row_style(row):
        style_str = TYPE_COLOR_MAP.get(str(row.get("種別", "")).strip(), "")
        return [style_str] * len(row)
    return df_to_style.style.apply(row_style, axis=1)

df = load_data()
dual_owned_map = detect_all_dual_owned(df)

tab1, tab2, tab3 = st.tabs(["🔍 登録一覧・検索・二重所持判定", "➕ 1件登録", "📦 まとめて一括登録"])

with tab1:
    col_top1, col_top2 = st.columns([4, 1])
    with col_top1:
        st.subheader("登録済みデータの検索・巻数＆二重所持チェック")
    with col_top2:
        if st.button("🔄 最新データに更新"):
            st.cache_data.clear()
            st.rerun()

    col_s, col_f1, col_f2, col_f3 = st.columns([2, 1, 1, 1])
    with col_s:
        keyword = st.text_input("キーワード検索（例: 『かぐや様』『ToLOVEる』など）", placeholder="タイトル・サークル・CV・ID・備考で検索")
    with col_f1:
        type_list = ["すべて"] + sorted([x for x in df["種別"].unique() if x])
        type_filter = st.selectbox("種別で絞り込み", type_list)
    with col_f2:
        ed_list = ["すべて"] + sorted([x for x in df["版・仕様"].unique() if x])
        edition_filter = st.selectbox("版・仕様で絞り込み", ed_list)
    with col_f3:
        plat_list = ["すべて"] + sorted([x for x in df["購入元"].unique() if x])
        platform_filter = st.selectbox("購入元で絞り込み", plat_list)

    col_chk1, col_chk2 = st.columns([2, 1])
    with col_chk1:
        only_dual = st.checkbox(f"⚠️ 既に二重所持（通常＋特装版／別版／重複巻）している作品のみ表示（現在 {len(dual_owned_map)} 件該当）")
    with col_chk2:
        use_color = st.checkbox("🎨 種別ごとに色分け表示（漫画=青 / 小説=緑 / ボイス=桃）", value=True)

    filtered_df = df.copy()
    if only_dual:
        filtered_df = filtered_df.loc[filtered_df.index.isin(dual_owned_map.keys())].copy()
        filtered_df["二重所持の判定理由"] = [dual_owned_map.get(i, "") for i in filtered_df.index]

    if keyword:
        mask = (
            filtered_df["タイトル"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["固有ID"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["作者・サークル"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["CV・出演者"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["所持巻数"].str.contains(keyword, case=False, na=False, regex=False) |
            filtered_df["備考"].str.contains(keyword, case=False, na=False, regex=False)
        )
        filtered_df = filtered_df[mask]

    if type_filter != "すべて":
        filtered_df = filtered_df[filtered_df["種別"] == type_filter]

    if edition_filter != "すべて":
        filtered_df = filtered_df[filtered_df["版・仕様"] == edition_filter]

    if platform_filter != "すべて":
        filtered_df = filtered_df[filtered_df["購入元"] == platform_filter]

    st.write(f"表示件数: **{len(filtered_df)}** 件 / 全 **{len(df)}** 件")
    if use_color and not filtered_df.empty:
        st.dataframe(style_by_type(filtered_df), use_container_width=True, hide_index=True)
    else:
        st.dataframe(filtered_df, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("作品の1件登録")
    st.caption("※同じ巻の通常版と特装版を両方持っている場合は、版・仕様で『通常＋特装版（二重所持）』を選ぶか、所持巻数に『1〜10, 7(特装)』のように入力すると二重所持として自動判定されます。")
    with st.form("register_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            media_type = st.selectbox("種別", ["漫画", "小説", "ボイス/ASMR", "ゲーム", "その他"])
            edition = st.selectbox("版・仕様", EDITION_OPTIONS)
            item_id = st.text_input("固有ID（RJ番号 / ISBN / ASIN）", placeholder="例: RJ123456")
            title = st.text_input("タイトル *", placeholder="作品名を入力")
            volumes = st.text_input("所持巻数", placeholder="例: 1〜15 / 5, 10, 16 / 1〜10, 7(特装)")
        with col2:
            completed = st.selectbox("完結ステータス", ["", "★（完結）", "☆（一時完結・区切り）"])
            creator = st.text_input("作者・サークル名")
            cv = st.text_input("CV・出演者", placeholder="声優名など（複数可）")
            platform = st.selectbox("購入元", ["DLsite", "Amazon", "FANZA", "DMM", "BOOTH", "その他"])
            purchase_date = st.date_input("購入日", value=date.today())
            note = st.text_input("備考", placeholder="レーベル略称（JC, KC等）・セール情報・特典メモなど")

        force_submit = st.checkbox("重複・別仕様の警告を確認した上で登録する")
        submitted = st.form_submit_button("登録する")

    if submitted:
        if not title.strip():
            st.error("タイトルは必須項目です。")
        else:
            dup_warnings = check_duplicates(df, item_id, title, edition, volumes)
            if dup_warnings and not force_submit:
                st.warning("⚠️ 重複または別仕様の所持データが見つかりました！")
                for w in dup_warnings:
                    st.markdown(f"- {w}")
                st.info("特装版やフルカラー版など、あえて二重所持として追加登録する場合は「重複・別仕様の警告を確認した上で登録する」にチェックを入れて再度「登録する」を押してください。")
            else:
                comp_mark = "★" if "★" in completed else ("☆" if "☆" in completed else "")
                new_row = {
                    "固有ID": item_id.strip(),
                    "タイトル": title.strip(),
                    "種別": media_type,
                    "版・仕様": edition,
                    "所持巻数": volumes.strip(),
                    "完結": comp_mark,
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
                            st.success(f"『{title}』（{edition}）をスプレッドシートに登録しました！")
                            st.cache_data.clear()
                        else:
                            st.error(f"保存エラー: {res_json}")
                    except Exception as e:
                        st.error(f"通信エラーが発生しました: {e}")

with tab3:
    st.subheader("📦 まとめて一括登録")
    st.caption("DLsiteの購入履歴（全選択コピー）・RJ番号・DLsite Play本棚、またはAmazon等のタイトル一覧からまとめて一括登録できます。")

    if "bulk_df" not in st.session_state:
        st.session_state.bulk_df = pd.DataFrame(columns=COLUMNS)

    sub_a, sub_b = st.tabs(["🎧 方法A：DLsite（購入履歴丸ごとコピー / RJ番号）から自動取得", "📖 方法B：タイトル一覧テキストから一括作成"])

    with sub_a:
        rj_text = st.text_area(
            "DLsiteの購入履歴画面（Ctrl+Aで丸ごとコピーしたもの）、またはRJ/BJ番号リストをそのまま貼り付け",
            placeholder="・購入履歴ページの画面全体（Ctrl+A -> Ctrl+C）をそのまま貼り付けOK！\n（『購入日時』『評価する』『全額ポイント』などの不要な表文字は自動で全削除し、作品名と巻数を抽出します）\n・R-18作品もフィルターなしで完全に自動取得されます。",
            height=140
        )
        col_d1, col_d2 = st.columns([1, 2])
        with col_d1:
            dlsite_date = st.date_input("購入日（日付が取得できない場合用）", value=date.today(), key="dl_date")
        if st.button("① DLsiteテキストから作品・巻数情報を自動抽出"):
            # 1. まずRJ/BJ番号単体のリストがあるか判定
            codes = list(dict.fromkeys(re.findall(r"[RVB]J\d{6,8}", rj_text.upper())))
            if codes:
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
                    st.success(f"{len(new_rows)}件の作品情報を下のプレビュー表に追加しました！")
            else:
                # 2. 購入履歴テーブルまたはDLsite Play本棚の丸ごとコピペを自動解析
                parsed_rows = parse_dlsite_copied_text(rj_text, dlsite_date.strftime("%Y/%m/%d"))
                if parsed_rows:
                    st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(parsed_rows)], ignore_index=True)
                    st.success(f"購入履歴テーブルから不要な文字を除去し、{len(parsed_rows)} 件のシリーズ（同一作品の巻数を統合）をプレビュー表に追加しました！")
                else:
                    st.warning("作品データを抽出できませんでした。購入履歴ページでコピーしたテキストが入っているか確認してください。")

    with sub_b:
        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
        with col_b1:
            bulk_type = st.selectbox("一括設定する種別", ["漫画", "小説", "ボイス/ASMR", "ゲーム", "その他"], key="b_type")
        with col_b2:
            bulk_ed = st.selectbox("一括設定する版・仕様", EDITION_OPTIONS, key="b_ed")
        with col_b3:
            bulk_plat = st.selectbox("一括設定する購入元", ["Amazon", "DLsite", "DMM", "FANZA", "BOOTH", "その他"], key="b_plat")
        with col_b4:
            bulk_date = st.date_input("一括設定する購入日", value=date.today(), key="b_date")

        lines_text = st.text_area(
            "1行に1作品のタイトルを入力（『タイトル, 所持巻数, 作者名』のようにカンマやタブで区切ると巻数や作者も同時に入ります）",
            placeholder="例:\n〇〇の冒険, 1〜5, 山田太郎\n△△の日常, 1〜3(特装), 佐藤花子",
            height=130
        )
        if st.button("① 下のプレビュー表に追加"):
            lines = [line.strip() for line in lines_text.splitlines() if line.strip()]
            if not lines:
                st.warning("テキストを入力してください。")
            else:
                added_rows = []
                for line in lines:
                    parts = [p.strip() for p in re.split(r"[\t,、]", line)]
                    t_val = parts[0] if len(parts) > 0 else ""
                    v_val = parts[1] if len(parts) > 1 else ""
                    c_val = parts[2] if len(parts) > 2 else ""
                    added_rows.append({
                        "固有ID": "",
                        "タイトル": t_val,
                        "種別": bulk_type,
                        "版・仕様": bulk_ed,
                        "所持巻数": v_val,
                        "完結": "",
                        "作者・サークル": c_val,
                        "CV・出演者": "",
                        "購入元": bulk_plat,
                        "購入日": bulk_date.strftime("%Y/%m/%d"),
                        "備考": ""
                    })
                st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(added_rows)], ignore_index=True)
                st.success(f"{len(added_rows)}件を下のプレビュー表に追加しました！")

    st.subheader("登録前の確認・編集プレビュー表")
    st.caption("表のセルをダブルクリックして「版・仕様」や「所持巻数」を直接修正したり、末尾の「＋」で行を追加できます。")
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

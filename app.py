import streamlit as st
import pandas as pd
import requests
import re
import html
import unicodedata
from datetime import date, datetime, timedelta, timezone
from collections import Counter

st.set_page_config(page_title="電子データ購入管理", layout="wide")
st.title("📚 電子データ購入管理")

COLUMNS = [
    "固有ID",
    "タイトル",
    "年齢区分",
    "種別",
    "版・仕様",
    "所持巻数",
    "完結",
    "作者・サークル",
    "CV・出演者",
    "購入元",
    "購入日",
    "金額",
    "備考"
]

AGE_OPTIONS = ["全年齢", "R-18", "未設定"]
MEDIA_TYPES = ["漫画", "小説", "ボイス/ASMR", "ゲーム", "その他"]

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

PLATFORM_OPTIONS = ["DLsite", "Amazon", "FANZA", "DMM", "BOOTH", "その他"]

ACTION_OPTIONS = [
    "✨ 新規登録",
    "🔄 同サイト上書き補完（金額・年齢・巻数を更新）",
    "🎨 バージョン違い（別仕様として新規追加）",
    "⚠️ 別サイト/既存あり（別行として新規追加）",
    "⏭️ スキップ（登録しない）"
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

def format_clean_date(val):
    """GASから返るISO形式(2024-03-22T15:00:00.000Z)や表記揺れを日本時間の YYYY/MM/DD に統一する"""
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    # 1) ISO 8601 UTC形式 (例: 2024-03-22T15:00:00.000Z) -> JST (+9時間) に変換して YYYY/MM/DD
    m_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?Z?$", s)
    if m_iso:
        try:
            dt_utc = datetime(
                int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)),
                int(m_iso.group(4)), int(m_iso.group(5)), int(m_iso.group(6)),
                tzinfo=timezone.utc
            )
            dt_jst = dt_utc.astimezone(timezone(timedelta(hours=9)))
            return dt_jst.strftime("%Y/%m/%d")
        except Exception:
            pass
    # 2) YYYY/M/D, YYYY-M-D, YYYY年M月D日 形式 -> YYYY/MM/DD にゼロ埋め統一
    m_ymd = re.match(r"^(\d{4})[年/\-\.](\d{1,2})[月/\-\.](\d{1,2})日?", s)
    if m_ymd:
        return f"{int(m_ymd.group(1)):04d}/{int(m_ymd.group(2)):02d}/{int(m_ymd.group(3)):02d}"
    return s

@st.cache_data(ttl=60)
def load_data():
    try:
        res = requests.get(GAS_URL, timeout=30)
        res.raise_for_status()
        data = res.json()
        df = pd.DataFrame(data, columns=COLUMNS)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[COLUMNS].fillna("").astype(str)
        df = df[~((df["タイトル"] == "タイトル") & (df["固有ID"] == "固有ID"))].reset_index(drop=True)
        df["版・仕様"] = df["版・仕様"].apply(lambda x: x if x.strip() else "通常")
        df["購入日"] = df["購入日"].apply(format_clean_date)
        return df
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        return pd.DataFrame(columns=COLUMNS)

def add_row(row_dict):
    res = requests.post(GAS_URL, json=row_dict, timeout=90)
    res.raise_for_status()
    return res.json()

def normalize_base_title(title):
    """タイトルから【特装版】【フルカラー】【特典】や末尾の [サークル名]・省略記号（... / …）を取り除いたベース作品名を返す"""
    t = str(title).strip()
    t = re.sub(r"\s*\[[^\[\]]+\]$", "", t)
    t = re.sub(r"^[\[【\(（].*?(特典|無料|お試し|デジタルポスター|ポスター|DLsite).*?[\]】\)）]\s*", "", t)
    t = re.sub(r"[\[【\(（].*?(特装|限定|フルカラー|セミカラー|カラー|デジタル版|文庫|新装|愛蔵|完全版|特典|お試し|無料|ポスター|創業祭).*?[\]】\)）]", "", t)
    t = re.sub(r"[\[【\(（][^\]】\)）]*(特典|無料|お試し|創業祭)[^\]】\)）]*$", "", t)
    t = re.sub(r"\s*(特装版|限定版|フルカラー版?|セミカラー版?|カラー版|モノクロ版|文庫版|新装版|愛蔵版|完全版|豪華版|特盛版)$", "", t)
    t = re.sub(r"(\.{2,}|…+)$", "", t)
    return t.strip()

def normalize_for_search(s):
    """検索用：全角半角・大文字小文字・記号・スペースの揺れを吸収した文字列を返す"""
    t = unicodedata.normalize("NFKC", str(s)).lower()
    t = re.sub(r"[\s\u3000×x✕・〜~～\-－―_!！?？:：/／「」『』【】\[\]()（）,、.。・…]+", "", t)
    return t

def is_bonus_or_trial_row(row):
    t = str(row.get("タイトル", ""))
    v = str(row.get("所持巻数", ""))
    p = str(row.get("金額", ""))
    if re.search(r"(特典|ポスター|無料|お試し|創業祭)", t) or v == "特典" or p == "0":
        return True
    return False

def detect_edition_from_title(title_str):
    if "セミカラー" in title_str:
        return "セミカラー"
    if "フルカラー" in title_str or "カラー版" in title_str or "極彩色" in title_str:
        return "フルカラー"
    if "特装版" in title_str or "限定版" in title_str or "豪華版" in title_str or "特盛版" in title_str:
        return "特装版・限定版"
    if "文庫" in title_str or "新装版" in title_str or "愛蔵版" in title_str:
        return "文庫・新装版"
    return "通常"

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

def merge_volume_strings(old_vol_str, new_vol_str):
    old_s = str(old_vol_str).strip()
    new_s = str(new_vol_str).strip()
    if not old_s:
        return new_s
    if not new_s or old_s == new_s:
        return old_s
    old_exp, _ = parse_volume_tokens(old_s)
    new_exp, _ = parse_volume_tokens(new_s)
    combined = old_exp + new_exp
    if combined and all(re.match(r"^\d+$", x) for x in combined):
        return compress_int_volumes([int(x) for x in combined])
    return new_s

def detect_all_dual_owned(df):
    """
    重複・関連所持を4つの明確なカテゴリに分類し、
    『どの作品（タイトル・サイト・種別・版・巻数）と重なっているか』を返す
    戻り値: dict[index] -> {"category": str, "detail": str, "base_title": str}
    """
    base_titles = df["タイトル"].apply(normalize_base_title)
    title_counts = Counter([bt for bt in base_titles if bt])

    info_per_index = {}
    for idx, row in df.iterrows():
        bt = base_titles.loc[idx]
        ed = str(row["版・仕様"]).strip()
        vol_str = str(row["所持巻数"]).strip()
        details = []
        cat = None

        if bt and title_counts[bt] >= 2:
            group_rows = df[base_titles == bt]
            other_rows = group_rows.drop(index=idx)
            types = set(group_rows["種別"])
            bonuses = [is_bonus_or_trial_row(r) for _, r in group_rows.iterrows()]
            eds = set(group_rows["版・仕様"])

            if any(bonuses) and not all(bonuses):
                cat = "🎁 特典・無料版とのセット"
            elif len(types) >= 2:
                cat = "📚 別メディア（漫画/小説/ボイス）"
            elif any("カラー" in e or "文庫" in e for e in eds):
                cat = "🎨 カラー版・文庫版（仕様違い）"
            else:
                cat = "🚨 要確認（通常＋特装版／別サイト重複）"

            partner_descs = []
            for _, r in other_rows.iterrows():
                p_plat = r["購入元"] or "Keepメモ"
                p_type = r["種別"]
                p_ed = r["版・仕様"]
                p_vol = f" / {r['所持巻数']}" if str(r["所持巻数"]).strip() else ""
                partner_descs.append(f"『{r['タイトル']}』({p_plat}・{p_type}・{p_ed}{p_vol})")
            details.append("相手: " + " ｜ ".join(partner_descs[:3]))

        _, dup_vols = parse_volume_tokens(vol_str)
        if dup_vols:
            if not cat:
                cat = "🚨 要確認（通常＋特装版／別サイト重複)"
            details.append(f"同一行内で巻数重複・別仕様あり({', '.join(dup_vols)})")

        if ("＋" in ed or "+" in ed or "二重" in ed) and not cat:
            cat = "🚨 要確認（通常＋特装版／別サイト重複）"
            details.append(f"仕様欄で二重所持({ed})")

        if cat:
            info_per_index[idx] = {
                "category": cat,
                "detail": " / ".join(details),
                "base_title": bt or str(row["タイトル"])
            }
    return info_per_index

def annotate_bulk_actions(df_existing, new_rows_list):
    annotated = []
    for item in new_rows_list:
        row_copy = {col: str(item.get(col, "")).strip() for col in COLUMNS}
        in_id = row_copy["固有ID"].upper()
        in_title = row_copy["タイトル"]
        in_base = normalize_base_title(in_title)
        in_ed = row_copy["版・仕様"] or "通常"
        in_plat = row_copy["購入元"]

        action = "✨ 新規登録"
        same_site_same_ed = None
        same_base_diff_ed = None
        diff_site_match = None

        for _, ex in df_existing.iterrows():
            ex_id = str(ex["固有ID"]).strip().upper()
            ex_title = str(ex["タイトル"]).strip()
            ex_base = normalize_base_title(ex_title)
            ex_ed = str(ex["版・仕様"]).strip() or "通常"
            ex_plat = str(ex["購入元"]).strip()

            id_matched = bool(in_id and ex_id and in_id == ex_id)
            title_matched = bool(
                in_base and ex_base and (
                    in_base.lower() == ex_base.lower()
                    or (len(in_base) >= 5 and in_base.lower() in ex_base.lower())
                    or (len(ex_base) >= 5 and ex_base.lower() in in_base.lower())
                )
            )

            if id_matched or title_matched:
                if ex_plat == in_plat and ex_ed == in_ed:
                    same_site_same_ed = ex
                    break
                elif ex_ed != in_ed:
                    same_base_diff_ed = ex
                else:
                    diff_site_match = ex

        if same_site_same_ed is not None:
            action = "🔄 同サイト上書き補完（金額・年齢・巻数を更新）"
            row_copy["所持巻数"] = merge_volume_strings(same_site_same_ed["所持巻数"], row_copy["所持巻数"])
            if not row_copy["金額"] and str(same_site_same_ed.get("金額", "")).strip():
                row_copy["金額"] = str(same_site_same_ed["金額"]).strip()
            if not row_copy["年齢区分"] and str(same_site_same_ed.get("年齢区分", "")).strip():
                row_copy["年齢区分"] = str(same_site_same_ed["年齢区分"]).strip()
        elif same_base_diff_ed is not None:
            action = "🎨 バージョン違い（別仕様として新規追加）"
            prev_ed = same_base_diff_ed["版・仕様"]
            prev_plat = same_base_diff_ed["購入元"] or "未設定"
            note_add = f"別仕様所持あり({prev_plat}:{prev_ed})"
            if note_add not in row_copy["備考"]:
                row_copy["備考"] = f"{row_copy['備考']} / {note_add}".strip(" /")
        elif diff_site_match is not None:
            action = "⚠️ 別サイト/既存あり（別行として新規追加）"
            prev_plat = diff_site_match["購入元"] or "Keepメモ(購入元未設定)"
            prev_vol = diff_site_match["所持巻数"] or "巻数未設定"
            note_add = f"他枠所持あり({prev_plat}: {prev_vol})"
            if note_add not in row_copy["備考"]:
                row_copy["備考"] = f"{row_copy['備考']} / {note_add}".strip(" /")

        row_with_action = {"処理区分": action}
        row_with_action.update(row_copy)
        annotated.append(row_with_action)
    return annotated

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
            row_plat = str(row["購入元"]).strip() or "未設定"
            row_vols_str = str(row["所持巻数"]).strip()
            row_vols, _ = parse_volume_tokens(row_vols_str)

            if base_input and row_base and (
                base_input.lower() == row_base.lower()
                or (len(base_input) >= 4 and base_input.lower() in row_base.lower())
                or (len(row_base) >= 4 and row_base.lower() in base_input.lower())
            ):
                overlap_vols = sorted(set(new_vols) & set(row_vols))
                if row_ed != edition:
                    warnings.append(
                        f"【別仕様の所持あり】『{row_title}』は既に **[{row_ed}]**（購入元: {row_plat} / 所持巻: {row_vols_str or '未設定'}）で登録されています。"
                        f"（今回: [{edition}] との二重所持になります）"
                    )
                elif overlap_vols:
                    warnings.append(
                        f"【同一巻の重複】『{row_title}』[{row_ed}]（購入元: {row_plat}）の **{', '.join(overlap_vols)}巻** は既に所持しています！"
                        f"（登録済み巻: {row_vols_str}）"
                    )
                else:
                    warnings.append(
                        f"【同一作品あり】『{row_title}』[{row_ed}]（購入元: {row_plat} / 登録済み巻: {row_vols_str or '未設定'}）が登録されています。"
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

                    age_cat = str(item.get("age_category", ""))
                    if age_cat == "1" or site in ["home", "comic"]:
                        age_str = "全年齢"
                    else:
                        age_str = "R-18"

                    price_val = str(item.get("price", "")) if item.get("price") is not None else ""
                    edition = detect_edition_from_title(title)
                    creator_str = " / ".join(authors) if authors else maker

                    return {
                        "固有ID": rj_id,
                        "タイトル": title,
                        "年齢区分": age_str,
                        "種別": media_type,
                        "版・仕様": edition,
                        "所持巻数": "",
                        "完結": "",
                        "作者・サークル": creator_str,
                        "CV・出演者": " / ".join(cvs),
                        "購入元": "DLsite",
                        "購入日": date.today().strftime("%Y/%m/%d"),
                        "金額": price_val,
                        "備考": maker if (authors and maker and maker not in authors) else ""
                    }
        except Exception:
            continue
    return {
        "固有ID": rj_id,
        "タイトル": "（自動取得失敗：手動で入力してください）",
        "年齢区分": "未設定",
        "種別": "ボイス/ASMR",
        "版・仕様": "通常",
        "所持巻数": "",
        "完結": "",
        "作者・サークル": "",
        "CV・出演者": "",
        "購入元": "DLsite",
        "購入日": date.today().strftime("%Y/%m/%d"),
        "金額": "",
        "備考": ""
    }

def classify_dlsite_type(tag_text):
    if any(k in tag_text for k in ["ボイス", "ASMR", "音楽", "音素材", "音声"]):
        return "ボイス/ASMR"
    if any(k in tag_text for k in ["ノベル", "小説", "文芸", "ラノベ"]):
        return "小説"
    if any(k in tag_text for k in ["ゲーム", "ロールプレイング", "シミュレーション", "アクション", "アドベンチャー", "シューティング", "パズル", "クイズ", "テーブル", "タイピング"]):
        return "ゲーム"
    if any(k in tag_text for k in ["動画", "アニメ", "ツール"]):
        return "その他"
    return "漫画"

def consolidate_series_rows(raw_items, platform_name):
    """抽出した作品リストから同一シリーズの巻数（単巻・パック・第N話）と購入金額を自動で1行にまとめる"""
    grouped = {}
    order_keys = []

    for it in raw_items:
        t = it["title"].strip()
        # タイトル末尾に [サークル名] が残っている場合は分離する
        m_br = re.match(r"^(.*?)\s*\[([^\[\]]+)\]$", t)
        if m_br:
            t = m_br.group(1).strip()
            if not it.get("maker") or it.get("maker") == t:
                it["maker"] = m_br.group(2).strip()

        t_norm = t.translate(str.maketrans("０１２３４５６７８９（）", "0123456789()"))
        p_val = it.get("price")
        age_val = it.get("age", "")
        ed_val = detect_edition_from_title(t)

        m_pack_range = re.match(r"^(.*?)[\s　]*(\d+)(?:巻)?[〜~～\-](\d+)巻パック(.*)$", t_norm)
        m_pack_single = re.match(r"^(.*?)[\s　]*(\d+)巻パック(.*)$", t_norm)
        m_vol_tag = re.match(r"^(.*?)\s*[Vv]ol\.?\s*(\d+)\s*(【.*?】)?$", t_norm)
        m_ep = re.match(r"^(.*?)\s*第(\d+)話(.*)$", t_norm)
        m_trail = re.match(r"^(.*?)(?:[\s　]+(\d+)巻?|\((\d+)\))(?:[\s　]*【comipo限定特典付き】)?$", t_norm)

        if not it.get("owned_cnt") and m_pack_range and m_pack_range.group(1).strip():
            base_t = (m_pack_range.group(1).strip() + " " + m_pack_range.group(4).strip()).strip()
            s_v, e_v = int(m_pack_range.group(2)), int(m_pack_range.group(3))
            key = ("VOL", base_t, it["maker"], it["mtype"], ed_val)
            if key not in grouped:
                grouped[key] = {"vols": [], "prices": [], "age": age_val, "date": it["date"], "ed": ed_val}
                order_keys.append(key)
            grouped[key]["vols"].extend(range(s_v, e_v + 1))
            if p_val is not None:
                grouped[key]["prices"].append(p_val)
        elif not it.get("owned_cnt") and m_pack_single and m_pack_single.group(1).strip():
            base_t = (m_pack_single.group(1).strip() + " " + m_pack_single.group(3).strip()).strip()
            e_v = int(m_pack_single.group(2))
            key = ("VOL", base_t, it["maker"], it["mtype"], ed_val)
            if key not in grouped:
                grouped[key] = {"vols": [], "prices": [], "age": age_val, "date": it["date"], "ed": ed_val}
                order_keys.append(key)
            grouped[key]["vols"].extend(range(1, e_v + 1))
            if p_val is not None:
                grouped[key]["prices"].append(p_val)
        elif not it.get("owned_cnt") and m_vol_tag and m_vol_tag.group(1).strip():
            base_t = f"{m_vol_tag.group(1).strip()}{m_vol_tag.group(3) or ''}".strip()
            v_num = int(m_vol_tag.group(2))
            key = ("VOL", base_t, it["maker"], it["mtype"], ed_val)
            if key not in grouped:
                grouped[key] = {"vols": [], "prices": [], "age": age_val, "date": it["date"], "ed": ed_val}
                order_keys.append(key)
            grouped[key]["vols"].append(v_num)
            if p_val is not None:
                grouped[key]["prices"].append(p_val)
        elif not it.get("owned_cnt") and m_ep and not m_ep.group(3).strip():
            base_t = m_ep.group(1).strip()
            ep_num = int(m_ep.group(2))
            key = ("EP", base_t, it["maker"], it["mtype"], ed_val)
            if key not in grouped:
                grouped[key] = {"eps": [], "prices": [], "age": age_val, "date": it["date"], "ed": ed_val}
                order_keys.append(key)
            grouped[key]["eps"].append(ep_num)
            if p_val is not None:
                grouped[key]["prices"].append(p_val)
        elif not it.get("owned_cnt") and m_trail and m_trail.group(1).strip():
            base_t = m_trail.group(1).strip()
            v_num = int(m_trail.group(2) or m_trail.group(3))
            key = ("VOL", base_t, it["maker"], it["mtype"], ed_val)
            if key not in grouped:
                grouped[key] = {"vols": [], "prices": [], "age": age_val, "date": it["date"], "ed": ed_val}
                order_keys.append(key)
            grouped[key]["vols"].append(v_num)
            if p_val is not None:
                grouped[key]["prices"].append(p_val)
        else:
            key = ("SINGLE", t, it["maker"], it["mtype"], len(order_keys))
            grouped[key] = {
                "vols": [],
                "prices": [p_val] if p_val is not None else [],
                "age": age_val,
                "date": it["date"],
                "ed": ed_val,
                "owned_cnt": it.get("owned_cnt"),
                "total_cnt": it.get("total_cnt"),
                "exact_title": t,
                "extra_note": it.get("note", "")
            }
            order_keys.append(key)

    final_rows = []
    for key in order_keys:
        g = grouped[key]
        title_out = g.get("exact_title", key[1])
        maker_out = key[2]
        mtype_out = key[3]

        notes = []
        if g.get("extra_note"):
            notes.append(g["extra_note"])
        if title_out.endswith("...") or title_out.endswith("…"):
            notes.append("※タイトル末尾省略あり")

        if g.get("vols"):
            vol_str = compress_int_volumes(g["vols"])
        elif g.get("eps"):
            vol_str = f"第{compress_int_volumes(g['eps'])}話"
        elif g.get("owned_cnt"):
            vol_str = f"計{g['owned_cnt']}冊（巻数未展開）"
            notes.append(f"Play集約({g['owned_cnt']}/{g['total_cnt']})")
        else:
            vol_str = ""

        total_price_str = str(sum(g["prices"])) if g.get("prices") else ""

        final_rows.append({
            "固有ID": "",
            "タイトル": title_out,
            "年齢区分": g.get("age", ""),
            "種別": mtype_out,
            "版・仕様": g.get("ed", "通常"),
            "所持巻数": vol_str,
            "完結": "",
            "作者・サークル": maker_out,
            "CV・出演者": "",
            "購入元": platform_name,
            "購入日": g["date"],
            "金額": total_price_str,
            "備考": " / ".join(notes)
        })
    return final_rows

def parse_dlsite_copied_text(text, fallback_date, default_age="自動判別"):
    """
    DLsiteの購入履歴テーブル（タブ区切り・サムネイル文字混在）またはDLsite Play本棚の
    全選択コピーをブロック単位で正確に解析し、タイトル・サークル名・金額・年齢区分を抽出する
    """
    if not text.strip():
        return []

    block_pat = re.compile(r"(\d{4}/\d{1,2}/\d{1,2})(?=\s|\t|$)")
    play_date_pat = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s*購入")

    raw_items = []

    # パターン1: 購入履歴テーブル（2026/08/24 形式の日付ブロック）
    if block_pat.search(text):
        parts = block_pat.split(text)
        for k in range(1, len(parts), 2):
            d_raw = parts[k]
            body = parts[k + 1] if k + 1 < len(parts) else ""
            m_d = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})", d_raw)
            d_str = f"{int(m_d.group(1)):04d}/{int(m_d.group(2)):02d}/{int(m_d.group(3)):02d}"

            # 1) サムネイル画像の "作品名 [サークル・出版社名]" パターンがあればそこから正確に分離
            m_alt = re.search(r"([^\r\n\t]+?)\s*\[([^\[\]\r\n\t]+)\]", body)
            if m_alt:
                raw_t = re.sub(r"^\d{1,2}:\d{2}\s*", "", m_alt.group(1)).strip()
                maker = m_alt.group(2).strip()
                title = raw_t
            else:
                tokens = [re.sub(r"^\d{1,2}:\d{2}\s*", "", seg).strip() for seg in re.split(r"[\r\n\t]+", body)]
                tokens = [seg for seg in tokens if seg and seg != "-" and not re.match(r"^\d{1,2}[:：]\d{2}$", seg)]
                title = tokens[0] if len(tokens) > 0 else ""
                maker = tokens[1] if len(tokens) > 1 else ""

            if not title:
                continue

            # 2) タブ区切りや改行の中に含まれる金額（例: 792円, 1,320円, 0円）を抽出
            m_price = re.search(r"([\d,，]+)\s*円", body)
            item_price = int(m_price.group(1).replace(",", "").replace("，", "")) if m_price else None

            # 3) 年齢区分と種別の判定
            if default_age != "自動判別":
                age_val = default_age
            elif "全年齢" in body:
                age_val = "全年齢"
            elif "R-18" in body or "成人" in body or "R15" in body:
                age_val = "R-18"
            else:
                age_val = "R-18"

            mtype = classify_dlsite_type(body)

            raw_items.append({
                "title": title,
                "maker": maker,
                "mtype": mtype,
                "age": age_val,
                "price": item_price,
                "date": d_str,
                "owned_cnt": None,
                "total_cnt": None
            })

    # パターン2: DLsite Play本棚画面（2026年8月24日 購入 形式）
    else:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        meta_pat = re.compile(r"^(?:(\d+)/(\d+)作品)?.*?(マンガ・CG|ボイス・ASMR|ノベル|ゲーム|動画|音楽|ツール|その他).*?$")
        only_count_pat = re.compile(r"^(\d+)/(\d+)作品$")
        current_date = fallback_date
        buffer = []
        for line in lines:
            m_date = play_date_pat.match(line)
            if m_date:
                current_date = f"{int(m_date.group(1)):04d}/{int(m_date.group(2)):02d}/{int(m_date.group(3)):02d}"
                buffer = []
                continue

            m_meta = meta_pat.match(line)
            m_cnt = only_count_pat.match(line)
            if m_meta or m_cnt:
                owned_cnt = m_meta.group(1) if m_meta else m_cnt.group(1)
                total_cnt = m_meta.group(2) if m_meta else m_cnt.group(2)
                cat_str = m_meta.group(3) if m_meta else "マンガ・CG"
                if len(buffer) >= 2:
                    t_val = buffer[-2]
                    m_val = buffer[-1]
                elif len(buffer) == 1:
                    t_val = buffer[-1]
                    m_val = ""
                else:
                    continue

                mtype = classify_dlsite_type(cat_str)
                age_val = default_age if default_age != "自動判別" else ""
                raw_items.append({
                    "title": t_val,
                    "maker": m_val,
                    "mtype": mtype,
                    "age": age_val,
                    "price": None,
                    "date": current_date,
                    "owned_cnt": owned_cnt,
                    "total_cnt": total_cnt
                })
                buffer = []
            else:
                buffer.append(line)

    if not raw_items:
        return []
    return consolidate_series_rows(raw_items, "DLsite")

def parse_fanza_dmm_text(text, fallback_date, platform_name="FANZA"):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    date_pat = re.compile(r"^(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})日?(?:\s*購入)?")
    price_pat = re.compile(r"([\d,，]+)\s*円")
    cat_map = {
        "コミック": "漫画",
        "マンガ": "漫画",
        "マンガ・CG": "漫画",
        "同人誌": "漫画",
        "単行本": "漫画",
        "雑誌": "漫画",
        "CG": "漫画",
        "CG（イラスト）": "漫画",
        "CG・イラスト": "漫画",
        "ボイス": "ボイス/ASMR",
        "ボイス・ASMR": "ボイス/ASMR",
        "音声": "ボイス/ASMR",
        "音楽": "ボイス/ASMR",
        "ASMR": "ボイス/ASMR",
        "ノベル": "小説",
        "小説": "小説",
        "文芸・ラノベ": "小説",
        "ライトノベル": "小説",
        "ビジネス・実用": "小説",
        "ゲーム": "ゲーム",
        "動画": "その他",
        "アニメ": "その他",
        "アダルトアニメ": "その他",
        "写真集": "その他",
    }
    junk_words = {
        "ダウンロード", "ブラウザで読む", "ブラウザ視聴", "視聴する", "再生",
        "レビューを書く", "評価する", "お気に入り", "バスケット", "購入済み作品",
        "一覧", "新着順", "購入日順"
    }

    default_age = "R-18" if platform_name == "FANZA" else "全年齢"
    current_date = fallback_date
    raw_items = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m_date = date_pat.match(line)
        if m_date:
            current_date = f"{int(m_date.group(1)):04d}/{int(m_date.group(2)):02d}/{int(m_date.group(3)):02d}"
            i += 1
            continue

        if line in cat_map:
            mtype = cat_map[line]
            title = ""
            maker = ""
            item_price = None
            j = i + 1
            while j < len(lines):
                cand = lines[j]
                if date_pat.match(cand) or cand in cat_map:
                    break
                m_pr = price_pat.search(cand)
                if m_pr and cand.endswith("円"):
                    item_price = int(m_pr.group(1).replace(",", "").replace("，", ""))
                    j += 1
                    continue
                if cand in junk_words:
                    j += 1
                    continue
                if not title:
                    title = cand
                elif not maker:
                    maker = cand
                j += 1
            if title:
                raw_items.append({
                    "title": title,
                    "maker": maker,
                    "mtype": mtype,
                    "age": default_age,
                    "price": item_price,
                    "date": current_date
                })
            i = j
            continue
        i += 1

    if not raw_items:
        return []
    return consolidate_series_rows(raw_items, platform_name)

def parse_amazon_kindle_text(text, fallback_type="漫画", default_age="全年齢"):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    date_pat = re.compile(r"^(?:取得日|購入日|注文日)[:：]\s*(\d{4})年(\d{1,2})月(\d{1,2})日")
    junk_patterns = [
        "デバイスからの配信または削除", "削除", "その他のアクション",
        "デバイスに配信", "既読としてマーク", "未読としてマーク",
        "コレクションに追加する", "すべて選択する", "すべての選択を解除",
        "表示:", "並べ替え:", "コンテンツを検索", "進む"
    ]

    raw_items = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m_date = date_pat.search(line)
        if m_date:
            d_str = f"{int(m_date.group(1)):04d}/{int(m_date.group(2)):02d}/{int(m_date.group(3)):02d}"
            candidates = []
            for back_idx in range(i - 1, max(-1, i - 5), -1):
                prev_line = lines[back_idx]
                if any(j in prev_line for j in junk_patterns) or date_pat.search(prev_line):
                    break
                candidates.insert(0, prev_line)

            if len(candidates) >= 2:
                title = candidates[0]
                author = candidates[1]
            elif len(candidates) == 1:
                title = candidates[0]
                author = ""
            else:
                title = ""
                author = ""

            if title:
                raw_items.append({
                    "title": title,
                    "author": author,
                    "date": d_str
                })
        i += 1

    grouped = {}
    order_keys = []

    for it in raw_items:
        t = it["title"].strip()
        t_norm = t.translate(str.maketrans("０１２３４５６７８９（）", "0123456789()"))

        m_vol = re.search(r"[\(（](\d+)[\)）]", t_norm)
        v_num = None
        if m_vol:
            v_num = int(m_vol.group(1))
            base_t = (t_norm[:m_vol.start()] + t_norm[m_vol.end():]).strip()
        else:
            m_vol2 = re.search(r"(\d+)\s*巻", t_norm)
            if m_vol2:
                v_num = int(m_vol2.group(1))
                base_t = (t_norm[:m_vol2.start()] + t_norm[m_vol2.end():]).strip()
            else:
                base_t = t_norm

        label_match = re.search(r"[\(（](.+?Web|.+?コミックス|.+?文庫|.+?レーベル)[\)）]", base_t, re.IGNORECASE)
        label_str = ""
        if label_match:
            label_str = label_match.group(1)
            base_t = (base_t[:label_match.start()] + base_t[label_match.end():]).strip()

        if v_num is not None:
            key = (base_t, it["author"])
            if key not in grouped:
                grouped[key] = {"vols": [], "date": it["date"], "label": label_str}
                order_keys.append(key)
            grouped[key]["vols"].append(v_num)
        else:
            key = (base_t, it["author"], len(order_keys))
            grouped[key] = {"vols": [], "date": it["date"], "label": label_str, "exact_title": base_t}
            order_keys.append(key)

    final_rows = []
    for key in order_keys:
        g = grouped[key]
        title_out = g.get("exact_title", key[0])
        author_out = key[1]
        v_str = compress_int_volumes(g["vols"]) if g["vols"] else ""
        edition = detect_edition_from_title(title_out)
        final_rows.append({
            "固有ID": "",
            "タイトル": title_out,
            "年齢区分": default_age,
            "種別": fallback_type,
            "版・仕様": edition,
            "所持巻数": v_str,
            "完結": "",
            "作者・サークル": author_out,
            "CV・出演者": "",
            "購入元": "Amazon",
            "購入日": g["date"],
            "金額": "",
            "備考": g["label"]
        })
    return final_rows

def style_by_type(df_to_style):
    def row_style(row):
        style_str = TYPE_COLOR_MAP.get(str(row.get("種別", "")).strip(), "")
        return [style_str] * len(row)
    return df_to_style.style.apply(row_style, axis=1)

df = load_data()
dual_owned_map = detect_all_dual_owned(df)

tab1, tab2, tab3 = st.tabs(["🔍 登録一覧・検索・二重所持判定", "➕ 1件登録", "📦 まとめて一括登録（上書き補完対応）"])

with tab1:
    col_top1, col_top2 = st.columns([4, 1])
    with col_top1:
        st.subheader("登録済みデータの検索・巻数＆二重所持チェック")
    with col_top2:
        if st.button("🔄 最新データに更新"):
            st.cache_data.clear()
            st.rerun()

    # 買う前のまとめて所持チェッカー（折りたたみ式）
    with st.expander("🛒 買う前の「まとめて所持チェッカー」（セール時やカート内のダブり買い防止・登録はされません）", expanded=False):
        st.caption("買おうか迷っている作品タイトル（1行に1作品、またはショップ画面のコピー）を貼り付けると、手持ちの台帳と照合して『未所持』『所持済み』『カラー/別版で所持』『別メディアで所持』を一括判定します。")
        chk_text = st.text_area("チェックしたい作品名を入力（複数行OK）", placeholder="例:\n終末のハーレム\nキミイロ×ライバー\n化物語", height=100, key="pre_buy_check_input")
        if chk_text.strip():
            raw_lines = [l.strip() for l in chk_text.splitlines() if l.strip()]
            chk_results = []
            df_base_norm = df["タイトル"].apply(lambda x: normalize_for_search(normalize_base_title(x)))
            for q_line in raw_lines:
                q_base = normalize_for_search(normalize_base_title(q_line))
                if len(q_base) < 2:
                    continue
                matches = df[df_base_norm.apply(lambda eb: bool(eb and (q_base == eb or (len(q_base) >= 4 and (q_base in eb or eb in q_base)))))]
                if matches.empty:
                    chk_results.append({"入力タイトル": q_line, "判定": "🆕 未所持（登録なし）", "所持しているデータ詳細": "—"})
                else:
                    m_descs = []
                    for _, mr in matches.iterrows():
                        mp = mr["購入元"] or "Keepメモ"
                        mv = f" [{mr['所持巻数']}巻]" if str(mr["所持巻数"]).strip() else ""
                        mc = f"({mr['完結']})" if str(mr["完結"]).strip() else ""
                        m_descs.append(f"『{mr['タイトル']}』({mp} / {mr['種別']} / {mr['版・仕様']}{mv}{mc})")
                    chk_results.append({
                        "入力タイトル": q_line,
                        "判定": f"⚠️ 所持データあり（{len(matches)}件）",
                        "所持しているデータ詳細": " ｜ ".join(m_descs)
                    })
            if chk_results:
                st.dataframe(pd.DataFrame(chk_results), use_container_width=True, hide_index=True)

    col_s, col_f0, col_f1, col_f2, col_f3 = st.columns([2.2, 1, 1, 1, 1])
    with col_s:
        keyword = st.text_input("キーワード検索（スペース区切りで複数語AND・記号/表記揺れ自動吸収）", placeholder="例: キミイロライバー / 集英社 カラー / 嘘つき屋")
    with col_f0:
        age_filter = st.selectbox("年齢区分", ["すべて", "全年齢のみ", "R-18のみ", "未設定のみ"])
    with col_f1:
        type_list = ["すべて"] + sorted([x for x in df["種別"].unique() if x])
        type_filter = st.selectbox("種別", type_list)
    with col_f2:
        ed_list = ["すべて"] + sorted([x for x in df["版・仕様"].unique() if x])
        edition_filter = st.selectbox("版・仕様", ed_list)
    with col_f3:
        plat_list = ["すべて"] + sorted([x for x in df["購入元"].unique() if x])
        platform_filter = st.selectbox("購入元", plat_list)

    # 重複・関連所持の内訳カウント
    cat_counts = Counter([v["category"] for v in dual_owned_map.values()])
    real_dup_count = sum(1 for v in dual_owned_map.values() if v["category"].startswith(("🚨", "🎨")))

    col_chk1, col_chk2, col_chk3 = st.columns([2.2, 1.3, 1.2])
    with col_chk1:
        only_dual = st.checkbox(f"⚠️ 重複・別版・関連所持で絞り込む（要確認・仕様違い: {real_dup_count}件 ／ 全関連: {len(dual_owned_map)}件）")
    with col_chk2:
        show_cards = st.checkbox("📱 検索結果をカード形式でも表示（15件以下の時）", value=True)
    with col_chk3:
        use_color = st.checkbox("🎨 種別ごとに色分け表示", value=True)

    filtered_df = df.copy()
    if only_dual:
        dup_mode = st.radio(
            "表示する重複・関連の区分（ペアごとに上下隣り合わせで並びます）",
            [
                f"🚨 要確認＋🎨 カラー・仕様違いのみ（{real_dup_count}件：特典・別メディアを除外）",
                f"🚨 要確認（通常＋特装版／別サイト重複）のみ（{cat_counts.get('🚨 要確認（通常＋特装版／別サイト重複）', 0)}件）",
                f"🎨 カラー版・文庫版（仕様違い）のみ（{cat_counts.get('🎨 カラー版・文庫版（仕様違い）', 0)}件）",
                f"📚 別メディア（漫画⇔小説・ボイス）のみ（{cat_counts.get('📚 別メディア（漫画/小説/ボイス）', 0)}件）",
                f"🎁 特典・無料版とのセットのみ（{cat_counts.get('🎁 特典・無料版とのセット', 0)}件）",
                f"すべて表示（全 {len(dual_owned_map)} 件）"
            ],
            horizontal=True
        )
        selected_indices = []
        for idx_k, info_v in dual_owned_map.items():
            c_str = info_v["category"]
            if dup_mode.startswith("🚨 要確認＋🎨"):
                if c_str.startswith(("🚨", "🎨")):
                    selected_indices.append(idx_k)
            elif dup_mode.startswith("🚨 要確認（"):
                if c_str.startswith("🚨"):
                    selected_indices.append(idx_k)
            elif dup_mode.startswith("🎨"):
                if c_str.startswith("🎨"):
                    selected_indices.append(idx_k)
            elif dup_mode.startswith("📚"):
                if c_str.startswith("📚"):
                    selected_indices.append(idx_k)
            elif dup_mode.startswith("🎁"):
                if c_str.startswith("🎁"):
                    selected_indices.append(idx_k)
            else:
                selected_indices.append(idx_k)

        filtered_df = filtered_df.loc[filtered_df.index.isin(selected_indices)].copy()
        filtered_df["重複・関連の区分"] = [dual_owned_map[i]["category"] for i in filtered_df.index]
        filtered_df["重なり相手・詳細"] = [dual_owned_map[i]["detail"] for i in filtered_df.index]
        filtered_df["_sort_base"] = [dual_owned_map[i]["base_title"] for i in filtered_df.index]
        filtered_df = filtered_df.sort_values(by=["重複・関連の区分", "_sort_base", "タイトル"]).drop(columns=["_sort_base"])
        # 見やすいように「重複・関連の区分」「重なり相手・詳細」をタイトルのすぐ右に配置
        front_cols = ["固有ID", "タイトル", "重複・関連の区分", "重なり相手・詳細"]
        rest_cols = [c for c in filtered_df.columns if c not in front_cols]
        filtered_df = filtered_df[front_cols + rest_cols]

    if age_filter == "全年齢のみ":
        filtered_df = filtered_df[filtered_df["年齢区分"] == "全年齢"]
    elif age_filter == "R-18のみ":
        filtered_df = filtered_df[filtered_df["年齢区分"] == "R-18"]
    elif age_filter == "未設定のみ":
        filtered_df = filtered_df[~filtered_df["年齢区分"].isin(["全年齢", "R-18"])]

    if keyword.strip():
        q_tokens = [tok for tok in re.split(r"[\s\u3000]+", keyword.strip()) if tok]
        combined_raw = (
            filtered_df["タイトル"] + " " +
            filtered_df["固有ID"] + " " +
            filtered_df["作者・サークル"] + " " +
            filtered_df["CV・出演者"] + " " +
            filtered_df["版・仕様"] + " " +
            filtered_df["購入元"] + " " +
            filtered_df["所持巻数"] + " " +
            filtered_df["備考"]
        )
        combined_norm = combined_raw.apply(normalize_for_search)
        mask = pd.Series(True, index=filtered_df.index)
        for qt in q_tokens:
            qt_norm = normalize_for_search(qt)
            token_match = combined_raw.str.contains(qt, case=False, na=False, regex=False)
            if qt_norm:
                token_match = token_match | combined_norm.str.contains(qt_norm, case=False, na=False, regex=False)
            mask = mask & token_match
        filtered_df = filtered_df[mask]

    if type_filter != "すべて":
        filtered_df = filtered_df[filtered_df["種別"] == type_filter]

    if edition_filter != "すべて":
        filtered_df = filtered_df[filtered_df["版・仕様"] == edition_filter]

    if platform_filter != "すべて":
        filtered_df = filtered_df[filtered_df["購入元"] == platform_filter]

    total_yen = sum(
        int(re.sub(r"[^\d]", "", str(x)))
        for x in filtered_df["金額"]
        if re.sub(r"[^\d]", "", str(x))
    )
    st.write(f"表示件数: **{len(filtered_df)}** 件 / 全 **{len(df)}** 件　｜　💰 表示中の合計金額: **{total_yen:,}** 円")

    # 検索結果が15件以下のとき（かつキーワード入力時または重複絞り込み時）、横スクロール不要のパッと見カードを表示
    if show_cards and (keyword.strip() or only_dual) and 1 <= len(filtered_df) <= 15:
        with st.container():
            st.caption("📱 **パッと見カード表示**（横スクロールなしで所持巻数・仕様・重なり相手を確認できます）")
            for idx_row, r in filtered_df.iterrows():
                vol_badge = f"📚 所持: **{r['所持巻数']}**" if str(r["所持巻数"]).strip() else "📚 単巻/巻数記載なし"
                comp_badge = f"（{r['完結']}）" if str(r["完結"]).strip() else ""
                plat_badge = r["購入元"] if str(r["購入元"]).strip() else "Keepメモ(購入元未設定)"
                p_digits = re.sub(r"[^\d]", "", str(r["金額"]))
                price_badge = f" ｜ 💰 {int(p_digits):,}円" if p_digits else ""
                dup_info = dual_owned_map.get(idx_row)
                dup_line = f"  \n👉 **{dup_info['category']}** — {dup_info['detail']}" if dup_info else ""
                st.markdown(
                    f"- **{r['タイトル']}** 　`{r['種別']}` `{r['版・仕様']}` `{r['年齢区分'] or '未設定'}`  \n"
                    f"　{vol_badge}{comp_badge} ｜ 🏢 {r['作者・サークル'] or '—'} ｜ 🛒 **{plat_badge}**{price_badge}{dup_line}"
                )

    if use_color and not filtered_df.empty:
        st.dataframe(style_by_type(filtered_df), use_container_width=True, hide_index=True)
    else:
        st.dataframe(filtered_df, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("作品の1件登録")
    with st.form("register_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            age_rating = st.selectbox("年齢区分", AGE_OPTIONS)
            media_type = st.selectbox("種別", MEDIA_TYPES)
            edition = st.selectbox("版・仕様", EDITION_OPTIONS)
            item_id = st.text_input("固有ID（RJ番号 / ISBN / ASIN）", placeholder="例: RJ123456")
            title = st.text_input("タイトル *", placeholder="作品名を入力")
            volumes = st.text_input("所持巻数", placeholder="例: 1〜15 / 5, 10, 16 / 1〜10, 7(特装)")
        with col2:
            completed = st.selectbox("完結ステータス", ["", "★（完結）", "☆（一時完結・区切り）"])
            creator = st.text_input("作者・サークル名")
            cv = st.text_input("CV・出演者", placeholder="声優名など（複数可）")
            platform = st.selectbox("購入元", PLATFORM_OPTIONS)
            purchase_date = st.date_input("購入日", value=date.today())
            price_input = st.text_input("金額（円）", placeholder="例: 792")
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
                st.info("特装版や別サイト購入分として登録する場合は「重複・別仕様の警告を確認した上で登録する」にチェックを入れて再度「登録する」を押してください。")
            else:
                comp_mark = "★" if "★" in completed else ("☆" if "☆" in completed else "")
                clean_price = re.sub(r"[^\d]", "", price_input.strip())
                new_row = {
                    "_action": "insert",
                    "固有ID": item_id.strip(),
                    "タイトル": title.strip(),
                    "年齢区分": "" if age_rating == "未設定" else age_rating,
                    "種別": media_type,
                    "版・仕様": edition,
                    "所持巻数": volumes.strip(),
                    "完結": comp_mark,
                    "作者・サークル": creator.strip(),
                    "CV・出演者": cv.strip(),
                    "購入元": platform,
                    "購入日": purchase_date.strftime("%Y/%m/%d"),
                    "金額": clean_price,
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
    st.subheader("📦 まとめて一括登録（重複自動判定＆上書き補完対応）")
    st.caption("既に登録済みの作品をもう一度貼り付けた場合、同じサイト・同じ仕様なら『金額』『年齢区分』『追加巻数』を自動で既存行に上書き補完します。")

    BULK_COLS = ["処理区分"] + COLUMNS
    if "bulk_df" not in st.session_state or list(st.session_state.bulk_df.columns) != BULK_COLS:
        st.session_state.bulk_df = pd.DataFrame(columns=BULK_COLS)
    if "input_ver" not in st.session_state:
        st.session_state.input_ver = 0
    if "editor_ver" not in st.session_state:
        st.session_state.editor_ver = 0
    if "bulk_flash_msg" in st.session_state and st.session_state.bulk_flash_msg:
        st.success(st.session_state.bulk_flash_msg)
        st.session_state.bulk_flash_msg = ""

    iv = st.session_state.input_ver

    sub_a, sub_b, sub_c, sub_d = st.tabs([
        "🎧 方法A：DLsite（購入履歴 / 本棚）",
        "🔞 方法B：FANZA / DMM（購入済み一覧）",
        "📦 方法C：Amazon Kindle（コンテンツ管理）",
        "✍️ 方法D：手入力・その他（1行1作品）"
    ])

    with sub_a:
        rj_text = st.text_area(
            "DLsiteの購入履歴画面（Ctrl+Aで丸ごとコピーしたもの）、またはRJ/BJ番号リストを貼り付け",
            placeholder="・購入履歴ページの画面全体（Ctrl+A -> Ctrl+C）をそのまま貼り付けOK！\n・サムネイル文字（作品名 [サークル名]）からタイトルとサークル名を自動分離し、タブ区切り内の『792円』などの金額もすべて自動抽出します。\n・抽出成功時にこの入力欄は自動でクリアされます。",
            height=140,
            key=f"dl_text_{iv}"
        )
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            dlsite_age_mode = st.selectbox("年齢区分の設定", ["自動判別（全年齢タグがあれば全年齢、なければR-18）", "すべて全年齢にする", "すべてR-18にする"], key="dl_age")
        with col_d2:
            dlsite_date = st.date_input("購入日（日付が取得できない場合用）", value=date.today(), key="dl_date")

        if st.button("① DLsiteテキストから作品・金額・年齢区分を自動抽出"):
            age_override = "自動判別"
            if "すべて全年齢" in dlsite_age_mode:
                age_override = "全年齢"
            elif "すべてR-18" in dlsite_age_mode:
                age_override = "R-18"

            codes = list(dict.fromkeys(re.findall(r"[RVB]J\d{6,8}", rj_text.upper())))
            if codes:
                new_rows = []
                prog = st.progress(0, text="DLsiteから作品情報を取得中...")
                for i, code in enumerate(codes):
                    info = fetch_dlsite_info(code)
                    info["購入日"] = dlsite_date.strftime("%Y/%m/%d")
                    if age_override != "自動判別":
                        info["年齢区分"] = age_override
                    new_rows.append(info)
                    prog.progress((i + 1) / len(codes), text=f"取得中 ({i + 1}/{len(codes)}): {code}")
                prog.empty()
                annotated_rows = annotate_bulk_actions(df, new_rows)
                st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(annotated_rows)], ignore_index=True)
                st.session_state.input_ver += 1
                st.session_state.editor_ver += 1
                st.session_state.bulk_flash_msg = f"DLsiteから {len(annotated_rows)} 件の作品情報をプレビュー表に追加し、テキスト欄をクリアしました！"
                st.rerun()
            else:
                parsed_rows = parse_dlsite_copied_text(rj_text, dlsite_date.strftime("%Y/%m/%d"), default_age=age_override)
                if parsed_rows:
                    annotated_rows = annotate_bulk_actions(df, parsed_rows)
                    st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(annotated_rows)], ignore_index=True)
                    st.session_state.input_ver += 1
                    st.session_state.editor_ver += 1
                    st.session_state.bulk_flash_msg = f"DLsiteのテキストから {len(annotated_rows)} 件（金額・年齢区分・重複判定付き）をプレビュー表に追加し、テキスト欄をクリアしました！"
                    st.rerun()
                else:
                    st.warning("作品データを抽出できませんでした。購入履歴ページでコピーしたテキストが入っているか確認してください。")

    with sub_b:
        fanza_text = st.text_area(
            "FANZA / DMMの購入済み一覧でコピーしたテキスト（日付・コミック/ボイス/ゲーム・作品名・サークル名）を貼り付け",
            placeholder="例:\n2026年08月24日\nコミック\n愛が重すぎる彼女達に温泉旅館に缶詰にされた時の話\n全角14字",
            height=140,
            key=f"fz_text_{iv}"
        )
        col_fz1, col_fz2 = st.columns(2)
        with col_fz1:
            fanza_plat = st.selectbox("購入元の選択（FANZA=R-18 / DMM=全年齢）", ["FANZA", "DMM"], key="fz_plat")
        with col_fz2:
            fanza_date = st.date_input("購入日（日付行がない場合用）", value=date.today(), key="fz_date")
        if st.button("① FANZA/DMMテキストから作品を自動抽出"):
            fz_rows = parse_fanza_dmm_text(fanza_text, fanza_date.strftime("%Y/%m/%d"), platform_name=fanza_plat)
            if fz_rows:
                annotated_rows = annotate_bulk_actions(df, fz_rows)
                st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(annotated_rows)], ignore_index=True)
                st.session_state.input_ver += 1
                st.session_state.editor_ver += 1
                st.session_state.bulk_flash_msg = f"{fanza_plat}の画面コピーから {len(annotated_rows)} 件の作品をプレビュー表に追加し、テキスト欄をクリアしました！"
                st.rerun()
            else:
                st.warning("作品を抽出できませんでした。「コミック」「ボイス」「ゲーム」などの種別行が含まれているか確認してください。")

    with sub_c:
        amz_text = st.text_area(
            "Amazonの「コンテンツと端末の管理（本の一覧）」で画面全体（Ctrl+A -> Ctrl+C）をコピーしたテキストを貼り付け",
            placeholder="・Amazonの「コンテンツと端末の管理」の画面全体をCtrl+A -> Ctrl+Cでコピーしてそのままペースト！",
            height=140,
            key=f"amz_text_{iv}"
        )
        col_am1, col_am2 = st.columns(2)
        with col_am1:
            amz_type = st.selectbox("一括設定する種別", ["漫画", "小説", "その他"], key="amz_type_select")
        with col_am2:
            amz_age = st.selectbox("一括設定する年齢区分", ["全年齢", "R-18"], key="amz_age_select")
        if st.button("① Amazonテキストから作品・巻数情報を自動抽出"):
            amz_rows = parse_amazon_kindle_text(amz_text, fallback_type=amz_type, default_age=amz_age)
            if amz_rows:
                annotated_rows = annotate_bulk_actions(df, amz_rows)
                st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(annotated_rows)], ignore_index=True)
                st.session_state.input_ver += 1
                st.session_state.editor_ver += 1
                st.session_state.bulk_flash_msg = f"Amazonの画面コピーから {len(annotated_rows)} 件のシリーズをプレビュー表に追加し、テキスト欄をクリアしました！"
                st.rerun()
            else:
                st.warning("Amazonの購入データを抽出できませんでした。「取得日: ○年○月○日」を含むテキストが入っているか確認してください。")

    with sub_d:
        col_b0, col_b1, col_b2, col_b3, col_b4 = st.columns(5)
        with col_b0:
            bulk_age = st.selectbox("年齢区分", ["全年齢", "R-18"], key="b_age")
        with col_b1:
            bulk_type = st.selectbox("種別", MEDIA_TYPES, key="b_type")
        with col_b2:
            bulk_ed = st.selectbox("版・仕様", EDITION_OPTIONS, key="b_ed")
        with col_b3:
            bulk_plat = st.selectbox("購入元", PLATFORM_OPTIONS, key="b_plat")
        with col_b4:
            bulk_date = st.date_input("購入日", value=date.today(), key="b_date")

        lines_text = st.text_area(
            "1行に1作品のタイトルを入力（『タイトル, 所持巻数, 作者名, 金額』のようにカンマやタブで区切ると同時に入ります）",
            placeholder="例:\n〇〇の冒険, 1〜5, 山田太郎, 2500\n△△の日常, 1〜3(特装), 佐藤花子, 1800",
            height=130,
            key=f"lines_text_{iv}"
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
                    p_val = re.sub(r"[^\d]", "", parts[3]) if len(parts) > 3 else ""
                    added_rows.append({
                        "固有ID": "",
                        "タイトル": t_val,
                        "年齢区分": bulk_age,
                        "種別": bulk_type,
                        "版・仕様": bulk_ed,
                        "所持巻数": v_val,
                        "完結": "",
                        "作者・サークル": c_val,
                        "CV・出演者": "",
                        "購入元": bulk_plat,
                        "購入日": bulk_date.strftime("%Y/%m/%d"),
                        "金額": p_val,
                        "備考": ""
                    })
                annotated_rows = annotate_bulk_actions(df, added_rows)
                st.session_state.bulk_df = pd.concat([st.session_state.bulk_df, pd.DataFrame(annotated_rows)], ignore_index=True)
                st.session_state.input_ver += 1
                st.session_state.editor_ver += 1
                st.session_state.bulk_flash_msg = f"{len(annotated_rows)}件を下のプレビュー表に追加し、テキスト欄をクリアしました！"
                st.rerun()

    st.subheader("登録前の確認・編集プレビュー表")
    st.caption("左端の「処理区分」で、既存行への上書き補完（🔄）になるか新規追加（✨/🎨/⚠️）になるかを事前に確認・変更できます。")
    edited_df = st.data_editor(
        st.session_state.bulk_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "処理区分": st.column_config.SelectboxColumn("処理区分", options=ACTION_OPTIONS, width="medium"),
            "年齢区分": st.column_config.SelectboxColumn("年齢区分", options=["全年齢", "R-18", ""]),
            "種別": st.column_config.SelectboxColumn("種別", options=MEDIA_TYPES),
            "版・仕様": st.column_config.SelectboxColumn("版・仕様", options=EDITION_OPTIONS),
            "完結": st.column_config.SelectboxColumn("完結", options=["", "★", "☆"]),
            "購入元": st.column_config.SelectboxColumn("購入元", options=PLATFORM_OPTIONS),
        },
        key=f"bulk_editor_{st.session_state.editor_ver}"
    )

    col_act1, col_act2 = st.columns([2, 1])
    with col_act1:
        if st.button("🚀 ② プレビュー表の内容をスプレッドシートに反映する（新規＆上書き補完）", type="primary"):
            valid_rows = [
                row for _, row in edited_df.iterrows()
                if str(row.get("タイトル", "")).strip() and not str(row.get("処理区分", "")).startswith("⏭️")
            ]
            if not valid_rows:
                st.warning("反映対象のデータがありません。")
            else:
                payload_rows = []
                for row in valid_rows:
                    act_str = str(row.get("処理区分", ""))
                    mode = "upsert" if act_str.startswith("🔄") else "insert"
                    row_dict = {col: str(row.get(col, "")).strip() for col in COLUMNS}
                    row_dict["_action"] = mode
                    payload_rows.append(row_dict)

                with st.spinner(f"{len(payload_rows)} 件のデータをスプレッドシートへ一括反映中..."):
                    try:
                        res_json = add_row({"rows": payload_rows})
                        if res_json.get("status") == "success":
                            ins_c = res_json.get("inserted", 0)
                            upd_c = res_json.get("updated", 0)
                            st.session_state.bulk_df = pd.DataFrame(columns=BULK_COLS)
                            st.session_state.input_ver += 1
                            st.session_state.editor_ver += 1
                            st.session_state.bulk_flash_msg = f"✅ 完了！ 新規追加: {ins_c} 件 ／ 既存行の上書き補完: {upd_c} 件 を反映し、プレビュー表をクリアしました！"
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"保存エラー（プレビュー表は保持されています）: {res_json}")
                    except Exception as e:
                        st.error(f"通信エラーが発生しました（プレビュー表は保持されているため、そのまま再実行できます）: {e}")
    with col_act2:
        if st.button("🗑️ プレビュー表を空にする"):
            st.session_state.bulk_df = pd.DataFrame(columns=BULK_COLS)
            st.session_state.editor_ver += 1
            st.rerun()

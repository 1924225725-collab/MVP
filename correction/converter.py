# -*- coding: utf-8 -*-
"""
converter.py —— 把「原始人工词库 txt」转换成「程序可用 JSON」。

设计红线
--------
1. **只读原始词库，绝不写回**。默认读 `dictionary/raw/` 下的快照；
   也可用 `--source` 指向别处（例如桌面上的原始目录）。
2. 转换是**单向生成**：产出 `dictionary/converted_*.json`，原始文件永不被覆盖。
3. 只做「结构化 + 清洗」，**不在这里判断该不该替换**——那是 scorer/corrector 的事。

原始格式（三类，逐行）
----------------------
* 热词库.txt      `序号/标准词/变体1、变体2、变体3`
* 人物库.txt      `序号/标准名/(变体1 变体2 变体3)` 或 `序号/标准名/(谐音：A、B；外号：C)`
* 影视作品名.txt  `序号/标准名/(打错字：X；叫错：Y→Z；外号：W)`   ← 含大量**说明文字**，需过滤
* 书本.txt        当前为空（0 字节）→ 产出空条目列表，结构保持一致

统一输出（每条目）
------------------
{
  "canonical": "标准词",
  "aliases": ["可能错误词1", ...],
  "category": "hotword" | "person" | "book" | "movie",
  "priority": 0-3,
  "context_tags": ["person", "homophone", ...],
  "description": "原始括号内的说明（给人看）",
  "source": "人物库.txt:517",
  "updated_at": "2026-09-13",
  "is_pattern": false        # 标准词含 ×× / XX 占位符 → 不能直接字面匹配
}

用法
----
    python converter.py                     # 读 dictionary/raw/ → 写 dictionary/converted_*.json
    python converter.py --source <目录>      # 指定原始词库目录
    python converter.py --sync-raw           # 先把 --source 的文件同步进 raw/ 再转换
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 常量

UPDATED_AT = "2026-09-13"

HERE = Path(__file__).resolve().parent
DICT_DIR = HERE / "dictionary"
RAW_DIR = DICT_DIR / "raw"

# 输出文件名 → (原始文件名, category)
SOURCES = {
    "hot_words": ("热词库.txt", "hotword"),
    "people": ("人物库.txt", "person"),
    "books": ("书本.txt", "book"),
    "movies": ("影视作品名.txt", "movie"),
}

# 可选外部原始词库（--source 默认值，仅用于 --sync-raw）。
# 使用用户目录推导，避免把开发机绝对路径写入源码；也可显式传 --source。
EXTERNAL_SOURCE = Path.home() / "Documents" / "AI Live Clipper" / "词语库"

# 分类基础优先级：热词多义性最强 → 基础优先级最低
CATEGORY_BASE_PRIORITY = {"person": 2, "book": 2, "movie": 2, "hotword": 1}

# 领域提示：原始说明里出现这些词 → 给条目打上领域 tag（供 corrector 做上下文匹配）
DOMAIN_HINTS = {
    "game": ("游戏", "电竞", "网游", "手游", "端游", "副本", "排位", "赛季"),
    "livestream": ("主播", "直播", "带货", "弹幕", "榜一", "连麦"),
    "film": ("演员", "导演", "剧组", "票房", "上映", "影视"),
    "book": ("小说", "作者", "出版", "网文", "文学"),
    "anime": ("动漫", "番剧", "二次元", "声优", "漫画"),
}

# 标签 → context_tags
LABEL_TAGS = {
    "谐音": "homophone", "空耳": "homophone", "音译": "homophone",
    "外号": "nickname", "戏称": "nickname", "恶搞": "nickname", "又名": "nickname",
    "打错字": "typo", "叫错": "typo", "错": "typo", "识别错误": "typo", "读错": "typo",
}

# 说明性文字标记：命中即认为这不是「可替换的错误词」，而是给人看的注释
_NOTE_MARKERS = (
    "易读错", "常读成", "常读错", "读错", "读音", "读法", "难读", "拗口", "绕口",
    "争议", "误译", "曲解", "简称", "被叫", "常被", "含义", "翻译错误", "误解",
    "混淆", "平台", "片方", "演员名", "剧名", "片名", "书名", "主角", "角色名",
    "台词", "打错", "叫错", "谐音", "外号", "空耳", "戏称", "恶搞", "改名",
    "台译", "港译", "识别错误", "音译", "又名",
)

# 说明前缀：剥掉后剩下的可能还是真别名（例："常被叫白蛇传" → "白蛇传"）
_PREFIX_STRIP_RE = re.compile(
    r"^(?:常被叫|常被称作|常被称为|常被简称|常简称|也叫|也叫作|简称|误称|"
    r"常误作|常写作|易写成|一般叫|大家叫|俗称|常叫|被叫|常被)"
)

_PLACEHOLDER_RE = re.compile(r"[×✕✖]|XX")
_ENTRY_HEAD_RE = re.compile(r"^\s*(\d+)\s*/\s*(.*)$")
_LABEL_SPLIT_RE = re.compile(r"([^：:]{1,8})[：:](.*)")
_ARROW_RE = re.compile(r"(.+?)\s*(?:→|->|=>)\s*(.+)")
_QUOTES = "“”「」『』()（）<>《》[]【】\"' \t"


# ---------------------------------------------------------------- 基础工具

def _norm(text: str) -> str:
    """归一化：去空白与常见标点，仅用于比较是否同一个词。"""
    return re.sub(r"[\s·・\-—_.,，。、；;：:!！?？~～]", "", (text or "").strip().lower())


def _clean_token(token: str) -> str:
    """剥掉引号、说明前缀和多余空白。"""
    t = (token or "").strip()
    t = t.strip(_QUOTES)
    t = _PREFIX_STRIP_RE.sub("", t).strip()
    return t.strip(_QUOTES)


def _acceptable(token: str, canonical: str) -> bool:
    """判断一个候选变体是否够格当「别名」（过滤说明文字与高危短词）。"""
    if not token:
        return False
    if token == canonical or _norm(token) == _norm(canonical):
        return False
    if token.isdigit():                      # 纯数字（081 / 33）歧义太大
        return False
    if len(token) < 2:                       # 单字一律不收
        return False
    if re.fullmatch(r"[A-Za-z0-9 .'\-]+", token) and len(token) < 4:
        return False                         # 过短的英文/数字（two / ok）
    if re.fullmatch(r"[^\u4e00-\u9fffA-Za-z0-9]+", token):
        return False                         # 纯标点
    return True


def _has_note_marker(token: str) -> bool:
    return any(m in token for m in _NOTE_MARKERS)


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _shares_char(alias: str, canonical: str) -> bool:
    """
    ASR 错字几乎都保留至少一个原字（同音替换）。
    一个跟标准词**一个字都不重合**的中文别名，通常不是「听错了」，
    而是关联实体的外号（例：二丫 / 龙妈 → 权力的游戏），
    把它当别名会导致「二丫」被替换成整部剧名这种破坏性结果。
    非中文别名（英文/数字）不做此判断。
    """
    if not (_CJK_RE.search(alias) and _CJK_RE.search(canonical)):
        return True
    return bool(set(alias) & set(canonical))


def _split_variants(text: str) -> list[str]:
    """
    切分变体串。分隔符：、，,；; 以及 '/'。
    '/' 带**承接规则**：`number one/two` → `number one` + `number two`
    （单独留一个 "two" 会变成到处乱匹配的高危别名）。
    """
    out: list[str] = []
    for part in re.split(r"[、，,；;]", text or ""):
        # `魏劭→魏助/魏刀/魏勋` = 三组字级纠错，不是三个独立别名。
        # 先把箭头铺开，否则后面的 "魏刀"/"魏勋" 会被误当成整词别名（灾难性误替换）。
        arrow = _ARROW_RE.match(part)
        if arrow:
            src = arrow.group(1).strip()
            for dst in arrow.group(2).split("/"):
                dst = dst.strip()
                if dst:
                    out.append(f"{src}→{dst}")
            continue

        prev_kept: str | None = None
        for frag in part.split("/"):
            frag = frag.strip()
            if not frag:
                continue
            if (
                prev_kept
                and " " in prev_kept
                and len(frag) < 4
                and re.fullmatch(r"[A-Za-z0-9]+", frag)
            ):
                frag = f"{prev_kept.rsplit(' ', 1)[0]} {frag}"
            out.append(frag)
            prev_kept = frag
    return out


def _unwrap(variants: str) -> tuple[str, bool]:
    """去掉外层括号，返回 (内部文本, 是否带括号)。"""
    v = (variants or "").strip()
    if (v.startswith("(") and v.endswith(")")) or (v.startswith("（") and v.endswith("）")):
        return v[1:-1].strip(), True
    return v, False


def _apply_arrow(canonical: str, src: str, dst: str) -> str | None:
    """
    `X→Y` 是**字级别**纠错（如 `鳞→麟`），不是整词别名。
    只有箭头的一端出现在标准词里，才能生成整词别名；否则这条只是说明。
    """
    src, dst = (src or "").strip(), (dst or "").strip()
    if src and src in canonical:
        return canonical.replace(src, dst, 1)
    if dst and dst in canonical:
        return canonical.replace(dst, src, 1)
    return None


# ---------------------------------------------------------------- 逐行解析

def iter_raw_entries(text: str):
    """产出 (序号, 标准词, 变体原文)。跳过标题、分隔线、空行。"""
    for raw_line in text.splitlines():
        line = raw_line.strip().replace("**", "")
        if not line or line.startswith("---"):
            continue
        m = _ENTRY_HEAD_RE.match(line)
        if not m:
            continue                       # 标题行 / 说明行
        index = int(m.group(1))
        rest = m.group(2)
        if "/" not in rest:
            continue
        canonical, variants = rest.split("/", 1)
        yield index, canonical.strip(), variants.strip()


def extract_aliases(canonical: str, variants: str, strict: bool):
    """
    抽取别名。

    strict=True  （影视/书本）：说明文字多，必须过滤「注释性片段」
    strict=False （热词/人物）：括号里基本都是真变体，只做基本清洗

    返回 (aliases, labels, note_text)
    """
    inner, _ = _unwrap(variants)
    note_text = inner or variants.strip()
    labels: list[str] = []
    aliases: list[str] = []

    if not _LABEL_SPLIT_RE.search(inner):
        # ---- 无标签形式：`小羊哥 小杨哥 小杨哥儿` 或 `变体1、变体2`
        for tok in re.split(r"[\s、，,；;]+", inner):
            tok = _clean_token(tok)
            if _acceptable(tok, canonical) and (not strict or not _has_note_marker(tok)):
                aliases.append(tok)
        return aliases, labels, note_text

    # ---- 有标签形式：`谐音：A、B；外号：C；打错字：X→Y`
    for group in re.split(r"[；;]", inner):
        gm = _LABEL_SPLIT_RE.match(group.strip())
        if not gm:
            # 无冒号的残段（如 `常被简称/叫错`）→ 当说明
            continue
        label = gm.group(1).strip()
        content = gm.group(2).strip()
        labels.append(label)

        for raw_tok in _split_variants(content):
            tok = _clean_token(raw_tok)
            arrow = _ARROW_RE.match(tok)
            if arrow:
                made = _apply_arrow(canonical, arrow.group(1), arrow.group(2))
                if (
                    made
                    and _acceptable(made, canonical)
                    and (not strict or _shares_char(made, canonical))
                ):
                    aliases.append(made)
                continue                     # 生成不了就丢弃（只留作说明）
            if not _acceptable(tok, canonical):
                continue
            if strict and _has_note_marker(tok):
                continue
            if strict and not _shares_char(tok, canonical):
                continue                     # 关联实体外号，不是错字
            aliases.append(tok)

    return aliases, labels, note_text


def build_entry(index: int, canonical: str, variants: str, category: str, source_name: str):
    strict = category in ("movie", "book")
    aliases, labels, note = extract_aliases(canonical, variants, strict)

    # 去重、保序
    seen, uniq = set(), []
    for a in aliases:
        k = _norm(a)
        if k and k not in seen:
            seen.add(k)
            uniq.append(a)
    aliases = uniq

    # context_tags：分类 + 标签语义 + 领域提示
    tags = [category]
    for lb in labels:
        t = LABEL_TAGS.get(lb)
        if t and t not in tags:
            tags.append(t)
    haystack = f"{canonical} {variants}"
    for domain, kws in DOMAIN_HINTS.items():
        if any(k in haystack for k in kws) and domain not in tags:
            tags.append(domain)

    # priority：分类基础分 +1（错误变体被记录得越多，说明越容易听错），上限 3
    priority = CATEGORY_BASE_PRIORITY.get(category, 0)
    if len(aliases) >= 3:
        priority += 1
    priority = max(0, min(3, priority))

    return {
        "canonical": canonical,
        "aliases": aliases,
        "category": category,
        "priority": priority,
        "context_tags": tags,
        "description": note,
        "source": f"{source_name}:{index}",
        "updated_at": UPDATED_AT,
        "is_pattern": bool(_PLACEHOLDER_RE.search(canonical)),
    }


def convert_file(path: Path, category: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    entries, merged = [], 0
    by_canonical: dict[str, dict] = {}

    for index, canonical, variants in iter_raw_entries(text):
        entry = build_entry(index, canonical, variants, category, path.name)
        if not entry["canonical"]:
            continue
        key = _norm(entry["canonical"])
        if key in by_canonical:
            # 同一标准词重复出现 → 合并别名（保留首次出现的 source）
            exist = by_canonical[key]
            known = {_norm(a) for a in exist["aliases"]}
            for a in entry["aliases"]:
                if _norm(a) not in known:
                    exist["aliases"].append(a)
                    known.add(_norm(a))
            merged += 1
            continue
        by_canonical[key] = entry
        entries.append(entry)

    return {
        "meta": {
            "source_file": path.name,
            "source_path": str(path),
            "category": category,
            "converter": "correction/converter.py",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": UPDATED_AT,
            "entry_count": len(entries),
            "alias_count": sum(len(e["aliases"]) for e in entries),
            "duplicate_lines_merged": merged,
            "note": "原始词库未做任何修改；本文件为程序使用的生成物。",
        },
        "entries": entries,
    }


# ---------------------------------------------------------------- CLI

def sync_raw(source_dir: Path) -> int:
    """把外部原始词库复制进 dictionary/raw/（只增不删，原始文件只读）。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for _key, (filename, _cat) in SOURCES.items():
        src = source_dir / filename
        if src.exists():
            shutil.copy2(src, RAW_DIR / filename)
            copied += 1
        else:
            print(f"[warn] 缺少原始文件：{src}")
    return copied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="原始词库 → 程序可用 JSON（不修改原始文件）")
    ap.add_argument("--source", default=str(EXTERNAL_SOURCE),
                    help="原始词库目录（--sync-raw 时使用）")
    ap.add_argument("--out", default=str(DICT_DIR), help="输出目录")
    ap.add_argument("--sync-raw", action="store_true",
                    help="先把 --source 的文件同步进 dictionary/raw/")
    args = ap.parse_args(argv)

    if args.sync_raw:
        n = sync_raw(Path(args.source))
        print(f"[raw] 已同步 {n} 个原始文件 → {RAW_DIR}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    total_entries = total_aliases = 0
    for key, (filename, category) in SOURCES.items():
        src = RAW_DIR / filename
        if not src.exists():
            print(f"[skip] 无 {filename}")
            continue
        payload = convert_file(src, category)
        out_path = out_dir / f"converted_{key}.json"
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        n_e = payload["meta"]["entry_count"]
        n_a = payload["meta"]["alias_count"]
        total_entries += n_e
        total_aliases += n_a
        print(f"[ok] {filename:<16} → {out_path.name:<28} "
              f"条目 {n_e:>4}  别名 {n_a:>5}  合并重复 {payload['meta']['duplicate_lines_merged']}")

    print(f"\n合计：条目 {total_entries} / 别名 {total_aliases}（原始词库未改动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""latex_template —— 按目标 venue 取官方 LaTeX 类文件（.cls/.sty/.bst）到产物目录。

本机通常没有 TeX，无法在此编译；本内核的职责是把**正确的类文件**放进
`deliverables/`，使 paper.tex 在下游（Overleaf / 用户机器）能直接编译。

设计要点：
- venue 是**枚举 key**，不是任意 URL —— 只从内置 allowlist 的官方源下载（防 SSRF）。
- 解压只按 basename 落盘（忽略压缩包内路径），天然规避 zip-slip。
- 走环境代理（ALL_PROXY/HTTPS_PROXY，urllib 自动识别）；取不到就返回阻断错误，禁止静默降级。
- 带年份的源（neurips/icml）默认**探测当前能下到的最新一年**（顶会每年发新模板，绝不写死旧年）；
  要复现旧版才用 --year 钉某年。

CLI:  python latex_template.py --venue neurips --dest <dir> [--year 2025]
      → 打印 JSON：{"venue","placed":[...],"year","year_note","source","note"} 或 {"error":...}
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import sys
import urllib.request
import zipfile

# 只允许从这些 host 下载（防止把 venue 当任意 URL 打）
_ALLOWED_HOSTS = {
    "mirrors.ctan.org",
    "media.neurips.cc",
    "media.icml.cc",
    "raw.githubusercontent.com",
}

# 类文件后缀：下载/解压时只挑这些落盘
_CLASS_EXT = (".cls", ".sty", ".bst", ".clo", ".bbx", ".cbx")

# venue → 取源规格。kind:
#   "zip"     远端 zip，解压取类文件（members 可选过滤子串）
#   "files"   直接下若干文件
#   "manual"  无稳定可自动下的源 —— 给出处并阻断导出（fetch 不下载）
# {year} 占位由 --year（或 default_year）填充。
SOURCES: dict[str, dict] = {
    "neurips": {"kind": "zip", "url": "https://media.neurips.cc/Conferences/NeurIPS{year}/Styles.zip",
                "note": "NeurIPS 官方 Styles.zip（含 neurips_{year}.sty）"},
    "icml": {"kind": "zip", "url": "https://media.icml.cc/Conferences/ICML{year}/Styles/icml{year}.zip",
             "note": "ICML 官方 styles"},
    "asme": {"kind": "zip", "url": "https://mirrors.ctan.org/macros/latex/contrib/asmeconf.zip",
             "primary": "asmeconf.cls",
             "note": "CTAN asmeconf 官方维护包（ASME conference class + bibliography style）"},
    "ieee": {"kind": "zip", "url": "https://mirrors.ctan.org/macros/latex/contrib/IEEEtran.zip",
             "note": "CTAN IEEEtran（会议/期刊通用）"},
    # acmart 的 CTAN 包只含 acmart.dtx/.ins（源），不含现成 acmart.cls（需 `tex acmart.ins` 生成）。
    # 这里能直接拿到的是 ACM bst 系列；acmart.cls 由 Overleaf/TeXLive 内置提供。primary 缺失会触发 warning。
    "kdd": {"kind": "zip", "url": "https://mirrors.ctan.org/macros/latex/contrib/acmart.zip",
            "primary": "acmart.cls",
            "note": "KDD 用 \\documentclass[sigconf]{acmart}；acmart.cls 由 Overleaf/TeXLive 内置（CTAN 包内是 .dtx 源），此处取到的是 ACM 参考文献 .bst/.bbx/.cbx"},
    "sigir": {"kind": "zip", "url": "https://mirrors.ctan.org/macros/latex/contrib/acmart.zip",
              "primary": "acmart.cls",
              "note": "SIGIR 用 \\documentclass[sigconf]{acmart}；acmart.cls 同 KDD 由 Overleaf/TeXLive 内置"},
    "eccv": {"kind": "zip", "url": "https://mirrors.ctan.org/macros/latex/contrib/llncs.zip",
             "note": "Springer llncs（ECCV 旧版基于此；近年 ECCV 自带 eccv.cls，请核对当年作者包）"},
    "acl": {"kind": "files", "urls": [
        "https://raw.githubusercontent.com/acl-org/acl-style-files/master/acl.sty",
        "https://raw.githubusercontent.com/acl-org/acl-style-files/master/acl_natbib.bst",
    ], "note": "ACL 官方 style（ACL/EMNLP 通用）"},
    "emnlp": {"kind": "alias", "of": "acl"},
    "coling": {"kind": "alias", "of": "acl", "note": "COLING 近年沿用 ACL 体系；请核对当年官方包"},
    # ICLR：官方 Master-Template 仓库按年存 conference.sty/.bst（raw.github 已在白名单）。
    # year_probe 用 .sty 探最新可用年；.bst 某年缺失会被 files 容错跳过（natbib/fancyhdr 由 TeXLive 内置）。
    "iclr": {"kind": "files", "urls": [
        "https://raw.githubusercontent.com/ICLR/Master-Template/master/iclr{year}/iclr{year}_conference.sty",
        "https://raw.githubusercontent.com/ICLR/Master-Template/master/iclr{year}/iclr{year}_conference.bst",
    ], "note": "ICLR 官方 Master-Template；用 \\usepackage{iclr{year}_conference}"},
    # CVPR：官方 author-kit 仓库根目录 cvpr.sty（不带年份，每年沿用同名）。
    "cvpr": {"kind": "files", "urls": [
        "https://raw.githubusercontent.com/cvpr-org/author-kit/main/cvpr.sty",
    ], "note": "CVPR 官方 author-kit（cvpr.sty）；正文 \\usepackage[review]{cvpr} 等按需"},
    # TMLR：官方 style 仓库 tmlr.sty（正文用标准 article + tmlr.sty）。
    "tmlr": {"kind": "files", "urls": [
        "https://raw.githubusercontent.com/JmlrOrg/tmlr-style-file/main/tmlr.sty",
    ], "note": "TMLR 官方 tmlr.sty；正文用标准 article 类 + \\usepackage{tmlr}"},
    # 无稳定自动源：给出处并阻断导出，由上层先取得真实作者包。
    "aaai": {"kind": "manual",
             "where": "AAAI 当年 Author Kit（aaai.org，含 aaai{yy}.sty，如 aaai25.sty/aaai26.sty）；"
                      "无公开稳定镜像，需登录/逐年取"},
    "interspeech": {"kind": "manual", "where": "ISCA 官方 Interspeech 模板（interspeech.cls）"},
    "nature": {"kind": "manual", "where": "Nature 接收后提供模板；通常 article + naturemag.bst"},
    "science": {"kind": "manual", "where": "Science 接收后提供模板"},
}

# 归一化别名
_ALIASES = {
    "neurips_2024": "neurips", "icml2025": "icml", "emnlp": "emnlp",
    "asmeconf": "asme", "asme-idetc": "asme", "asmeidetc": "asme",
    "idetc": "asme", "idetc-cie": "asme",
}

# 带年份的源往回探多少年（顶会每年发新模板：默认取“当前能下到的最新一年”，而非写死某年）
_YEAR_WINDOW = 5


def _norm(venue: str) -> str:
    v = (venue or "").strip().lower().replace(" ", "")
    return _ALIASES.get(v, v)


def _current_year() -> int:
    return datetime.date.today().year


def _url_ok(url: str, timeout: int = 15) -> bool:
    """HEAD 探测该 URL 是否可达（仅白名单 host）。用于“最新年份”探测，不下载正文。"""
    try:
        _check_host(url)
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "famou-latex-template/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — 白名单 host
            return 200 <= getattr(r, "status", 200) < 400
    except Exception:
        return False


def _latest_available_year(url_tmpl: str) -> int | None:
    """从当年往回 _YEAR_WINDOW 年探测，返回第一个 {year} 填入后可达的年份；都不可达则 None。"""
    cur = _current_year()
    for y in range(cur, cur - _YEAR_WINDOW - 1, -1):
        if _url_ok(url_tmpl.replace("{year}", str(y))):
            return y
    return None


def resolve(venue: str, year: int | None = None, probe: bool = False) -> dict:
    """返回某 venue 的规格、填充 {year}。alias 解引用。

    年份语义（关键）：
    - 显式传 ``year`` → 钉该年（复现旧模板时用）。
    - 否则 ``probe=True``（联网）→ 探测并取**当前能下到的最新一年**（顶会每年发新模板）。
    - 否则（``probe=False``，离线/单测）→ 暂填**当年**作为名义值；真实下载由 ``fetch`` 探测校正。
    """
    key = _norm(venue)
    spec = SOURCES.get(key)
    if spec is None:
        return {
            "venue": key,
            "manual": True,
            "template_required": True,
            "error": f"尚未内置 {venue!r} 的自动模板下载源；这不表示该 venue 不受支持。",
            "next_step": (
                "请由 Agent 查找该 venue 对应年份和稿件类型的官方 author guidelines/author kit，"
                "核验官网来源后将完整模板放入产物目录，并从官方示例 .tex 开始写作；禁止用通用 article 替代。"
            ),
        }
    if spec.get("kind") == "alias":
        base = dict(SOURCES[spec["of"]])
        base["venue"] = key
        spec = base
    spec = dict(spec)
    spec["venue"] = key
    if "url" in spec and "{year}" in spec["url"]:
        if year:
            y = year
        elif probe:
            y = _latest_available_year(spec["url"])
            if not y:
                cur = _current_year()
                spec["error"] = (f"{key}：近 {_YEAR_WINDOW + 1} 年（{cur}..{cur - _YEAR_WINDOW}）"
                                 f"均未探测到官方模板，请核对官网或手动指定 --year")
                return spec
            spec["latest"] = True  # 标记此年份是“探测到的最新”，非钉死
        else:
            y = _current_year()
        spec["url"] = spec["url"].replace("{year}", str(y))
        spec["year"] = y
    # 同理支持 "files" 类型里带 {year} 的 urls（如 ICLR 按年的 conference.sty/.bst）。
    if "urls" in spec and any("{year}" in u for u in spec["urls"]):
        probe_tmpl = spec.get("year_probe") or next(u for u in spec["urls"] if "{year}" in u)
        if year:
            y = year
        elif probe:
            y = _latest_available_year(probe_tmpl)
            if not y:
                cur = _current_year()
                spec["error"] = (f"{key}：近 {_YEAR_WINDOW + 1} 年（{cur}..{cur - _YEAR_WINDOW}）"
                                 f"均未探测到官方模板，请核对官网或手动指定 --year")
                return spec
            spec["latest"] = True
        else:
            y = _current_year()
        spec["urls"] = [u.replace("{year}", str(y)) for u in spec["urls"]]
        spec["year"] = y
    return spec


def _check_host(url: str) -> None:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"拒绝下载非白名单 host：{host}")


def _get(url: str, timeout: int = 30) -> bytes:
    _check_host(url)
    # urllib 自动识别 ALL_PROXY/HTTPS_PROXY 等环境代理
    req = urllib.request.Request(url, headers={"User-Agent": "famou-latex-template/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _safe_dest(dest: str) -> str:
    """dest 必须落在 cwd 之内（防越权写）。"""
    root = os.path.realpath(os.getcwd())
    full = os.path.realpath(os.path.join(root, dest))
    if full != root and not full.startswith(root + os.sep):
        raise ValueError(f"dest 越出工作目录：{dest}")
    os.makedirs(full, exist_ok=True)
    return full


def _place_zip(data: bytes, dest: str) -> list[str]:
    placed: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for m in zf.namelist():
            # 跳过 macOS 打包垃圾：__MACOSX/ 目录与 ._xxx AppleDouble 资源叉文件
            if "__MACOSX" in m.split("/") or os.path.basename(m).startswith("._"):
                continue
            base = os.path.basename(m)  # 只取 basename → 规避 zip-slip
            if not base or not base.lower().endswith(_CLASS_EXT):
                continue
            with zf.open(m) as src:
                with open(os.path.join(dest, base), "wb") as out:
                    out.write(src.read())
            placed.append(base)
    return placed


def fetch(venue: str, dest: str, year: int | None = None) -> dict:
    """下载并把类文件落到 dest。返回 {venue, placed[], source, note} 或 {error}。

    年份：不传 ``year`` 时**探测最新可用年份**（顶会每年发新模板，避免拿到过时版本）；
    传了就钉该年。
    """
    spec = resolve(venue, year, probe=(year is None))
    if spec.get("error"):
        return spec
    kind = spec.get("kind")
    if kind == "manual":
        return {"venue": spec["venue"], "placed": [], "manual": True,
                "where": spec.get("where", ""),
                "error": "官方模板没有稳定自动源，必须先取得作者包后再导出论文。",
                "template_required": True,
                "note": "请从 venue 官方作者包取得主类文件和配套资源；禁止用 article 类替代。"}
    try:
        full = _safe_dest(dest)
    except ValueError as e:
        return {"venue": spec["venue"], "error": str(e)}
    try:
        placed: list[str] = []
        skipped: list[str] = []
        if kind == "zip":
            placed = _place_zip(_get(spec["url"]), full)
        elif kind == "files":
            for u in spec["urls"]:
                base = os.path.basename(u)
                try:
                    data = _get(u)
                except Exception:
                    skipped.append(base)  # 单个文件取不到（如某年没 .bst）→ 跳过，不让整体失败
                    continue
                with open(os.path.join(full, base), "wb") as out:
                    out.write(data)
                placed.append(base)
        else:
            return {"venue": spec["venue"], "error": f"未知 kind：{kind}"}
        if not placed:
            return {"venue": spec["venue"], "error": "下载成功但未发现类文件（源结构可能变了，请核对当年作者包）",
                    "source": spec.get("url") or spec.get("urls")}
        result = {"venue": spec["venue"], "placed": sorted(placed), "dest": dest,
                  "source": spec.get("url") or spec.get("urls"),
                  "year": spec.get("year"), "note": spec.get("note", "")}
        if skipped:
            result["skipped"] = sorted(skipped)  # 部分辅助文件未取到（通常 TeXLive 内置），见此
        if spec.get("year"):
            kind_word = "探测到的最新可用年份" if spec.get("latest") else "指定年份"
            result["year_note"] = f"使用 {spec['year']} 年模板（{kind_word}）"
        # 源里下到了文件，但缺该 venue 的主类文件（如 acmart.cls 需另行生成/由 TeXLive 提供）——别假装成功
        primary = spec.get("primary")
        if primary and primary not in placed:
            result["error"] = f"未取到必需主类文件 {primary}，禁止导出。"
            result["template_required"] = True
            result["next_step"] = "安装与目标 venue 匹配的官方作者包/TeX Live 组件后重试；禁止用 article 类替代"
        return result
    except Exception as e:  # 网络/解析失败 —— 返回阻断错误，禁止降级
        return {"venue": spec["venue"], "error": f"取模板失败：{type(e).__name__}: {e}",
                "source": spec.get("url") or spec.get("urls"),
                "template_required": True,
                "next_step": "修复网络/模板源或手动放入官方作者包后重试；禁止用 article 类替代"}


def main() -> int:
    ap = argparse.ArgumentParser(description="按 venue 取官方 LaTeX 类文件到产物目录")
    ap.add_argument("--venue", required=True, help="neurips/icml/ieee/acl/cvpr/...")
    ap.add_argument("--dest", required=True, help="落盘目录（须在工作目录内，如 research-runs/x/deliverables）")
    ap.add_argument("--year", type=int, default=None, help="带年份的源（neurips/icml）指定年份")
    args = ap.parse_args()
    print(json.dumps(fetch(args.venue, args.dest, args.year), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

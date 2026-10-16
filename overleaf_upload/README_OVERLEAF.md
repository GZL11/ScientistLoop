# Overleaf 设置（上传后先做这两步，否则编译失败）

1. **Menu → Compiler → XeLaTeX**（默认是 pdfLaTeX，会因为 \todo{} 里的中文报错）
2. **Menu → Main document → main.tex**

其余保持默认。Overleaf 自动跑 bibtex，不需要手动操作。

## 与本地仓库的唯一结构差异

本地把 `iclr2026_conference.sty` / `.bst` 放在 `style/` 子目录，靠 build.sh 的
TEXINPUTS/BSTINPUTS 找到；Overleaf 上这两个文件放在**根目录**（和 main.tex 同级），
所以 main.tex 一个字都不用改。除此之外文件结构完全一致。

## 没有上传的东西（都不参与编译）

build/、archive/、build.sh、main_article_backup.tex、style/TEMPLATE_REFERENCE.pdf、
以及 reference/ 下的调研材料与 outline_v1.md、CLAUDE.md。

## 页数与投稿约束

正文硬上限 9 页（不含参考文献与附录）。`\iclrfinalcopy` 必须保持注释——投稿双盲。
收尾清单在 main.tex 文件末尾。

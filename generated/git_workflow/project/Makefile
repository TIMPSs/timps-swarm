.PHONY: install hooks tag changelog release
install:
\tnpm install --save-dev @commitlint/{cli,config-conventional} husky

hooks:
\tpre-commit install
\tgit config core.hooksPath .githooks

tag:
\tgit fetch --tags && git tag --sort=-creatordate | head -1

changelog:
\tnpx conventional-changelog -p angular -i CHANGELOG.md -s

release:
\tnpx semantic-release

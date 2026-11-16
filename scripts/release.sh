#!/bin/bash
# 发布脚本：打 tag 并推送到默认分支 master。
# 源码版本是 1.3.0，但该版本尚未打 tag、尚未创建 GitHub Release。
# 只有在决定正式发版时才执行；本次对齐不运行本脚本，也不推送 tag。
set -e

VERSION="1.3.0"
echo "发布 v$VERSION..."

# 运行测试
cd "$(dirname "$0")/../server"
echo "运行测试..."
pytest tests/ -q 2>&1 | tail -5

# 打 tag
cd ..
git add -A
git commit -m "chore: release v$VERSION" --allow-empty
git tag -a "v$VERSION" -m "Release v$VERSION"

echo "推送..."
git push origin master
git push origin "v$VERSION"

echo "✅ v$VERSION 发布完成"
echo "GitHub Releases: https://github.com/cnchaoge/lanwatch_agent/releases"

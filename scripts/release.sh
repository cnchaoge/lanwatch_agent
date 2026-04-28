#!/bin/bash
# 发布脚本：打 tag + 推送
set -e

VERSION="1.0.0"
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
git push origin main
git push origin "v$VERSION"

echo "✅ v$VERSION 发布完成"
echo "GitHub Releases: https://github.com/cnchaoge/lanwatch_agent/releases"

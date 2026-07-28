# 简历生成工作台

这是一个前端可运行的最小可行版本，用于演示两种简历生成模式：

- 一键生成批量简历：根据内置职业池或自定义职业列表批量生成候选人简历。
- 指定职业名称生成单个简历：输入一个职业名称后生成一份定向简历。

当前版本使用本地规则生成器，便于先验证产品流程。后续可以把 `src/resumeEngine.js` 中的生成函数替换为大模型 API、岗位画像库或知识图谱检索结果。

## 启动

```bash
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:5188/
```

## 架构

- `src/App.jsx`：页面状态、两种模式、结果预览、导出。
- `src/resumeEngine.js`：简历生成核心逻辑。
- `src/styles.css`：完整响应式界面样式。
- `scripts/generate-resumes.mjs`：终端生成入口。

## 终端生成

单个简历：

```bash
npm run generate:single -- --role "AI 产品经理" --format all --out outputs/single_demo
```

批量简历：

```bash
npm run generate:batch -- --count 20 --roles "前端开发工程师,后端开发工程师,数据分析师" --format all
```

查看完整参数：

```bash
npm run generate -- --help
```

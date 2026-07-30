# 合成简历数据集后处理脚本

这些脚本用于把原始合成简历改造成可用于人岗匹配的数据集。

## 1. 对齐标准岗位

把 `synthetic_detailed_resumes.csv` 中的粗粒度目标岗位，对齐到岗位系统的 `standard_job_title`，并补充岗位大族和岗位技能画像。

```powershell
python "B:\揭榜挂帅\dataset\resume\scripts\align_synthetic_resumes_to_standard_jobs.py"
```

输出：

```text
dataset/resume/synthetic_detailed_resumes_aligned.csv
dataset/resume/synthetic_detailed_resumes_aligned.jsonl
dataset/resume/synthetic_detailed_resumes_aligned_report.json
```

## 2. 补齐全部标准岗位

检查标准岗位词典中的岗位是否都在简历数据集中出现；缺失岗位会按岗位语义补充生成样本。

```powershell
python "B:\揭榜挂帅\dataset\resume\scripts\ensure_resume_standard_job_coverage.py"
```

输出仍然覆盖：

```text
dataset/resume/synthetic_detailed_resumes_aligned.csv
dataset/resume/synthetic_detailed_resumes_aligned.jsonl
dataset/resume/synthetic_detailed_resumes_aligned_sample.csv
dataset/resume/synthetic_detailed_resumes_aligned_report.json
```

## 3. 扩充经验年限

基于已经对齐并补齐岗位的简历，生成约 3 万条经验年限增强版数据。字段保持和 `synthetic_detailed_resumes_aligned.csv` 一致。

```powershell
python "B:\揭榜挂帅\dataset\resume\scripts\build_resume_experience_30k.py"
```

输出：

```text
dataset/resume/synthetic_detailed_resumes_experience_30k.csv
```

经验年限覆盖：

```text
0, 1, 2, 3, 5, 8, 10 年
```

## 推荐使用

人岗匹配实验优先使用：

```text
dataset/resume/synthetic_detailed_resumes_experience_30k.csv
```

如果只需要较小规模数据，可使用：

```text
dataset/resume/synthetic_detailed_resumes_aligned.csv
```

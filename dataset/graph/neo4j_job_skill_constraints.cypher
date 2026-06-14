// Job-Skill graph constraints
CREATE CONSTRAINT job_id_unique IF NOT EXISTS
FOR (j:Job) REQUIRE j.job_id IS UNIQUE;

CREATE CONSTRAINT skill_name_unique IF NOT EXISTS
FOR (s:Skill) REQUIRE s.name IS UNIQUE;

// Example checks after import
MATCH (j:Job)-[r]->(s:Skill)
RETURN labels(j) AS job_labels, type(r) AS relation, labels(s) AS skill_labels, count(*) AS count
ORDER BY count DESC;

MATCH (j:Job)-[r]->(s:Skill)
RETURN j.job_title AS job, type(r) AS relation, s.name AS skill, r.evidence_sentence AS evidence
LIMIT 20;

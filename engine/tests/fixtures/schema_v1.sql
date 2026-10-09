-- Schéma SQLite du jalon #1 (avant chapitres), PRAGMA user_version = 0.
CREATE TABLE projects (
	id INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	style TEXT NOT NULL, 
	reading_direction VARCHAR(20) NOT NULL, 
	page_format VARCHAR(100) NOT NULL, 
	workflow_preset VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE characters (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	visual_description TEXT NOT NULL, 
	prompt_keywords JSON NOT NULL, 
	lora_name VARCHAR(255), 
	lora_weight FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
CREATE INDEX ix_characters_project_id ON characters (project_id);
CREATE TABLE pages (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	number INTEGER NOT NULL, 
	grid_template VARCHAR(100), 
	state VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, number), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
CREATE INDEX ix_pages_project_id ON pages (project_id);
CREATE TABLE character_images (
	id INTEGER NOT NULL, 
	character_id INTEGER NOT NULL, 
	path VARCHAR(500) NOT NULL, 
	original_name VARCHAR(255) NOT NULL, 
	content_type VARCHAR(50) NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(character_id) REFERENCES characters (id) ON DELETE CASCADE
);
CREATE INDEX ix_character_images_character_id ON character_images (character_id);
CREATE TABLE panels (
	id INTEGER NOT NULL, 
	page_id INTEGER NOT NULL, 
	"index" INTEGER NOT NULL, 
	description TEXT NOT NULL, 
	character_ids JSON NOT NULL, 
	shot_type VARCHAR(50), 
	dialogues JSON NOT NULL, 
	importance INTEGER NOT NULL, 
	bbox JSON, 
	bubble_zone JSON, 
	final_prompt TEXT, 
	generation_preset VARCHAR(100), 
	qc_score INTEGER, 
	state VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (page_id, "index"), 
	FOREIGN KEY(page_id) REFERENCES pages (id) ON DELETE CASCADE
);
CREATE INDEX ix_panels_page_id ON panels (page_id);
CREATE TABLE bubbles (
	id INTEGER NOT NULL, 
	panel_id INTEGER NOT NULL, 
	"order" INTEGER NOT NULL, 
	speaker_id INTEGER, 
	text TEXT NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	position JSON, 
	tail JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(panel_id) REFERENCES panels (id) ON DELETE CASCADE, 
	FOREIGN KEY(speaker_id) REFERENCES characters (id) ON DELETE SET NULL
);
CREATE INDEX ix_bubbles_panel_id ON bubbles (panel_id);
CREATE TABLE jobs (
	id INTEGER NOT NULL, 
	project_id INTEGER, 
	panel_id INTEGER, 
	step VARCHAR(30) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	error TEXT, 
	created_at DATETIME NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	duration_ms INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(panel_id) REFERENCES panels (id) ON DELETE CASCADE
);
CREATE INDEX ix_jobs_panel_id ON jobs (panel_id);
CREATE INDEX ix_jobs_project_id ON jobs (project_id);
CREATE TABLE panel_images (
	id INTEGER NOT NULL, 
	panel_id INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	path VARCHAR(500) NOT NULL, 
	seed INTEGER, 
	params JSON NOT NULL, 
	qc_score INTEGER, 
	qc_reasons JSON NOT NULL, 
	selected BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (panel_id, version), 
	FOREIGN KEY(panel_id) REFERENCES panels (id) ON DELETE CASCADE
);
CREATE INDEX ix_panel_images_panel_id ON panel_images (panel_id);

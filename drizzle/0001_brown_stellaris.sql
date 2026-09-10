CREATE TABLE `summaries_table` (
	`id` text PRIMARY KEY NOT NULL,
	`transcript_id` text NOT NULL,
	`time` integer,
	`raw_transcript` text,
	`polished` text,
	`reasoning` text,
	`summary` text
);

CREATE TABLE `transcripts_table` (
	`id` text PRIMARY KEY NOT NULL,
	`time` integer,
	`text` text NOT NULL,
	`corrected_text` text
);

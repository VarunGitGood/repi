-- Migration 003: Add pending_question column to investigations table
-- Supports the "awaiting_clarification" status for the ReAct loop

ALTER TABLE investigations
  ADD COLUMN IF NOT EXISTS pending_question TEXT;

// Runs inside freellmapi (cwd /app/server): premium live-catalog metadata as JSON, no keys.
import Database from "better-sqlite3";
const db = new Database("/app/server/data/freeapi.db", { readonly: true, fileMustExist: true });
const rows = db.prepare(`select platform, model_id id, intelligence_rank ir, speed_rank sr, context_window ctx, supports_tools tools,
  supports_vision vision, enabled, paid_input_per_m pin, rpd_limit rpd, source from models`).all();
const v = db.prepare("select value from settings where key='catalog_applied_version'").get();
process.stdout.write(JSON.stringify({ version: v && v.value, models: rows }));

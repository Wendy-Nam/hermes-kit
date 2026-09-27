// Runs inside freellmapi (cwd /app/server). Prints "<catalog_last_sync_ms> <requests in last 24h>".
import Database from "better-sqlite3";
const db = new Database("/app/server/data/freeapi.db", { readonly: true, fileMustExist: true });
const sync = db.prepare("select value from settings where key = 'catalog_last_sync_ms'").get();
const used = db.prepare("select count(*) n from requests where created_at >= datetime('now', '-1 day')").get();
console.log(`${Math.trunc(Number(sync?.value || 0))} ${used.n}`);

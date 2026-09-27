#!/usr/bin/env python3
"""hermes-kit: ported from the author's server; applied at image build (no backup copy).

Hermes plugins/platforms/discord/adapter_media.py 로컬 패치 (이미지 레이어 — 재생성 시 재실행, root로).

배경: 20MB를 넘는 영상(2026-09-25 selected_motion_preview.mp4 60.6MB)은 "너무 크다" 안내만 보내고
업로드를 포기했다. 영상이면 ffmpeg로 채널 한도의 90%에 맞춰 재인코딩해 보낸다. 실패하거나
너무 길어 화질이 안 나오면(영상 150kbps 미만) 원본 경로 그대로 → 기존 안내 문구 경로.

전체 블록 치환 → 임시파일 compile → 교체. 멱등.
"""
import sys
from pathlib import Path

T = Path("/opt/hermes/plugins/platforms/discord/adapter_media.py")
MARK = "async def _fit_video_to_limit("

OLD_CALL = """        filename = file_name or os.path.basename(file_path)
        rejected = await self._reject_oversized_upload(channel, file_path, filename)"""
NEW_CALL = """        # Local patch: shrink an oversized video to fit instead of refusing it.
        file_path = await self._fit_video_to_limit(channel, file_path)
        filename = file_name or os.path.basename(file_path)
        rejected = await self._reject_oversized_upload(channel, file_path, filename)"""

OLD_DEF = """    async def _send_file_attachment("""
NEW_DEF = """    async def _fit_video_to_limit(self, channel: Any, file_path: str) -> str:
        \"\"\"Local patch: re-encode an oversized video under the channel cap with ffmpeg.

        Returns the original path when it already fits, is not a video, would drop below
        150 kbps video, or encoding fails — the caller then sends the size notice as before.
        \"\"\"
        if os.path.splitext(file_path)[1].lower() not in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
            return file_path
        try:
            size = os.path.getsize(file_path)
        except OSError:
            return file_path
        limit = self._discord_upload_limit_bytes(channel)
        if size <= limit:
            return file_path
        out_path = os.path.splitext(file_path)[0] + ".discord.mp4"
        proc = None
        try:
            probe = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(probe.communicate(), 30)
            duration = float(out.strip())
            audio_kbps = 96
            video_kbps = int(limit * 0.9 * 8 / 1000 / duration) - audio_kbps
            if video_kbps < 150:
                logger.warning("[%s] %s is too long (%.0fs) to fit %d MB watchably", self.name,
                               os.path.basename(file_path), duration, limit // (1024 * 1024))
                return file_path
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-v", "error", "-i", file_path, "-vf", "scale=min(1280\\\\,iw):-2",
                "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k",
                "-bufsize", f"{2 * video_kbps}k", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                "-movflags", "+faststart", out_path,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await asyncio.wait_for(proc.communicate(), 600)
            if proc.returncode == 0 and os.path.getsize(out_path) <= limit:
                logger.info("[%s] Re-encoded %s: %.1f MB -> %.1f MB for Discord", self.name,
                            os.path.basename(file_path), size / 1048576, os.path.getsize(out_path) / 1048576)
                return out_path
            logger.warning("[%s] Video re-encode did not fit (rc=%s): %s", self.name, proc.returncode,
                           (err or b"")[-300:].decode(errors="replace"))
        except Exception:
            if proc is not None and proc.returncode is None:
                proc.kill()
            logger.warning("[%s] Video re-encode failed for %s", self.name, file_path, exc_info=True)
        return file_path

    async def _send_file_attachment("""


def main() -> int:
    if not T.exists():
        print(f"target not found: {T}")
        return 1  # hermes-kit: a missing target is base-version drift and fails the build
    src = T.read_text()
    if MARK in src:
        print("already patched:", T)
        return 0
    assert src.count(OLD_CALL) == 1 and src.count(OLD_DEF) == 1, "anchor not unique"
    out = src.replace(OLD_DEF, NEW_DEF, 1).replace(OLD_CALL, NEW_CALL, 1)
    compile(out, str(T), "exec")
    tmp = T.with_suffix(".py.tmp-video-fit")
    tmp.write_text(out)
    compile(tmp.read_text(), str(tmp), "exec")
    tmp.replace(T)
    print("patched:", T)
    return 0


if __name__ == "__main__":
    sys.exit(main())

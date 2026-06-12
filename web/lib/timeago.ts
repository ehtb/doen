export function timeago(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);

  if (diffSec < 60) return "just now";
  if (diffSec < 3600) {
    const m = Math.floor(diffSec / 60);
    return `${m} minute${m === 1 ? "" : "s"} ago`;
  }
  if (diffSec < 86400) {
    const h = Math.floor(diffSec / 3600);
    return `${h} hour${h === 1 ? "" : "s"} ago`;
  }
  if (diffSec < 2592000) {
    const d2 = Math.floor(diffSec / 86400);
    return `${d2} day${d2 === 1 ? "" : "s"} ago`;
  }
  if (diffSec < 31536000) {
    const mo = Math.floor(diffSec / 2592000);
    return `${mo} month${mo === 1 ? "" : "s"} ago`;
  }
  const y = Math.floor(diffSec / 31536000);
  return `${y} year${y === 1 ? "" : "s"} ago`;
}

export function isRecent(date: string | Date, days = 3): boolean {
  const d = typeof date === "string" ? new Date(date) : date;
  return Date.now() - d.getTime() < days * 86400 * 1000;
}

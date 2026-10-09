import { engineUrl } from "@/lib/api";

export function Avatar({ url, name, size = "h-9 w-9" }: { url?: string; name: string; size?: string }) {
  if (!url) {
    return (
      <span className={`flex ${size} shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-semibold text-zinc-400`}>
        {name.slice(0, 2).toUpperCase()}
      </span>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={engineUrl(url)} alt="" className={`${size} shrink-0 rounded-full object-cover`} />;
}

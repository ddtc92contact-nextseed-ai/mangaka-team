"use client";

import { useState, type ComponentProps } from "react";
import type { PanelCrop } from "@/lib/api";
import { imagePlacement } from "@/lib/crop";

/**
 * Image d'une case, cadrée comme à l'assemblage : centrée au remplissage (`object-cover`), ou selon le
 * cadrage manuel de la case (fenêtre centrée sur `crop`, zoom). Le parent doit être positionné et couper
 * ce qui dépasse (`overflow-hidden`). `boxWidth` × `boxHeight` : proportions de la case (px de la page).
 */
export function CroppedImage({
  src,
  crop,
  boxWidth,
  boxHeight,
  alt,
  className = "",
  ...props
}: {
  src: string;
  alt: string;
  crop: PanelCrop | null | undefined;
  boxWidth: number;
  boxHeight: number;
} & Omit<ComponentProps<"img">, "src" | "style" | "alt">) {
  const [size, setSize] = useState<{ src: string; w: number; h: number } | null>(null);
  const known = size && size.src === src ? size : null;
  const place = crop && known && boxWidth > 0 && boxHeight > 0 ? imagePlacement(known.w, known.h, boxWidth, boxHeight, crop) : null;
  const measure = (img: HTMLImageElement | null) => {
    if (img && img.complete && img.naturalWidth > 0 && (!known || known.w !== img.naturalWidth)) {
      setSize({ src, w: img.naturalWidth, h: img.naturalHeight });
    }
  };
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      {...props}
      alt={alt}
      ref={measure}
      src={src}
      onLoad={(e) => measure(e.currentTarget)}
      data-cropped={place ? "true" : undefined}
      className={place ? `absolute max-w-none ${className}` : `h-full w-full object-cover ${className}`}
      style={
        place
          ? {
              left: `${place.left * 100}%`,
              top: `${place.top * 100}%`,
              width: `${place.width * 100}%`,
              height: `${place.height * 100}%`,
            }
          : undefined
      }
    />
  );
}

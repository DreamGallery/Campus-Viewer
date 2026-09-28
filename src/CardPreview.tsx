import { useRef, useState } from "react";
import { X } from "lucide-react";
import type { Entry } from "./catalog";

export default function CardPreview({
  images,
  title,
}: {
  images: NonNullable<Entry["group_images"]>;
  title: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState(0);
  return (
    <>
      <div
        className="card-previews"
        style={{
          gridTemplateColumns: `repeat(${images.length}, minmax(0, 1fr))`,
        }}
      >
        {images.map((image, index) => (
          <button
            key={image.url}
            className="card-preview"
            aria-label={`放大 ${title} ${image.label}`}
            onClick={() => {
              setSelected(index);
              dialog.current?.showModal();
            }}
          >
            <img
              style={{aspectRatio: image.preview_crop ? 3 : image.aspect_ratio || undefined, objectFit: image.preview_crop ? "cover" : undefined, objectPosition: image.preview_crop || undefined}} src={image.url}
              alt={`${title} ${image.label}`}
              loading="lazy"
            />
            {images.length > 1 && <span>{image.label}</span>}
          </button>
        ))}
      </div>
      <dialog
        ref={dialog}
        className="card-lightbox"
        aria-label={`${title} 卡面预览`}
        onClick={(event) => {
          if (event.target === event.currentTarget) dialog.current?.close();
        }}
      >
        <div className="lightbox-toolbar">
          <span>{title}</span>
          <button
            autoFocus
            aria-label="关闭卡面预览"
            onClick={() => dialog.current?.close()}
          >
            <X />
          </button>
        </div>
        <img
          style={{aspectRatio: images[selected].aspect_ratio || undefined, width: images[selected].aspect_ratio ? `min(100%, ${75 * images[selected].aspect_ratio!}dvh)` : undefined}} src={images[selected].url}
          alt={`${title} ${images[selected].label}`}
        />
        {images.length > 1 && (
          <div className="lightbox-stages">
            {images.map((image, index) => (
              <button
                key={image.url}
                aria-pressed={selected === index}
                onClick={() => setSelected(index)}
              >
                {image.label}
              </button>
            ))}
          </div>
        )}
      </dialog>
    </>
  );
}

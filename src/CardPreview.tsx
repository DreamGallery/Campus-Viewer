import { useRef, useState, type CSSProperties } from "react";
import { X } from "lucide-react";
import type { Entry } from "./catalog";

export default function CardPreview({
  images,
  title,
  imageAspectRatio,
  zoomable = true,
}: {
  images: NonNullable<Entry["group_images"]>;
  title: string;
  imageAspectRatio?: number;
  zoomable?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const selectedImage = selected === null ? undefined : images[selected];
  const selectedAspectRatio = imageAspectRatio ?? selectedImage?.aspect_ratio;
  const PreviewContainer = zoomable ? "button" : "div";
  return (
    <>
      <div
        className="card-previews"
        style={{
          gridTemplateColumns: `repeat(${images.length}, minmax(0, 1fr))`,
        }}
      >
        {images.map((image, index) => {
          const aspectRatio = imageAspectRatio ?? (image.preview_crop ? 3 : image.aspect_ratio);
          return (
            <PreviewContainer
              key={image.url}
              className={`card-preview${zoomable ? "" : " card-preview-static"}`}
              style={{ "--card-preview-ratio": aspectRatio || 16 / 9 } as CSSProperties}
              aria-label={zoomable ? `放大 ${title} ${image.label}` : undefined}
              onClick={zoomable ? () => {
                setSelected(index);
                dialog.current?.showModal();
              } : undefined}
            >
              <img
                style={{aspectRatio: aspectRatio || undefined, objectFit: !imageAspectRatio && image.preview_crop ? "cover" : "fill", objectPosition: image.preview_crop || undefined}} src={image.url}
                alt={`${title} ${image.label}`}
                loading="lazy"
              />
              {images.length > 1 && <span>{image.label}</span>}
            </PreviewContainer>
          );
        })}
      </div>
      {zoomable && <dialog
        ref={dialog}
        className="card-lightbox"
        aria-label={`${title} 卡面预览`}
        onClose={() => setSelected(null)}
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
        {selectedImage && <img
          style={{aspectRatio: selectedAspectRatio || undefined, width: selectedAspectRatio ? `min(100%, ${75 * selectedAspectRatio}dvh)` : undefined, objectFit: imageAspectRatio ? "fill" : undefined}} src={selectedImage.url}
          alt={`${title} ${selectedImage.label}`}
          decoding="async"
        />}
        {selectedImage && images.length > 1 && (
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
      </dialog>}
    </>
  );
}

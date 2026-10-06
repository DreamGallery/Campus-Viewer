import { useRef, useState } from "react";
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
  const [selected, setSelected] = useState(0);
  const selectedAspectRatio = imageAspectRatio ?? images[selected].aspect_ratio;
  const PreviewContainer = zoomable ? "button" : "div";
  return (
    <>
      <div
        className="card-previews"
        style={{
          gridTemplateColumns: `repeat(${images.length}, minmax(0, 1fr))`,
        }}
      >
        {images.map((image, index) => (
          <PreviewContainer
            key={image.url}
            className={`card-preview${zoomable ? "" : " card-preview-static"}`}
            aria-label={zoomable ? `放大 ${title} ${image.label}` : undefined}
            onClick={zoomable ? () => {
              setSelected(index);
              dialog.current?.showModal();
            } : undefined}
          >
            <img
              style={{aspectRatio: imageAspectRatio ?? (image.preview_crop ? 3 : image.aspect_ratio || undefined), objectFit: imageAspectRatio ? "fill" : image.preview_crop ? "cover" : undefined, objectPosition: image.preview_crop || undefined}} src={image.url}
              alt={`${title} ${image.label}`}
              loading="lazy"
            />
            {images.length > 1 && <span>{image.label}</span>}
          </PreviewContainer>
        ))}
      </div>
      {zoomable && <dialog
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
          style={{aspectRatio: selectedAspectRatio || undefined, width: selectedAspectRatio ? `min(100%, ${75 * selectedAspectRatio}dvh)` : undefined, objectFit: imageAspectRatio ? "fill" : undefined}} src={images[selected].url}
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
      </dialog>}
    </>
  );
}

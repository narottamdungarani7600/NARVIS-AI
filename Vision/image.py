"""Image loading, transformation, and statistics helpers for NARVIS Vision."""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .vision import ImageFrame, _emit_log

try:
    from PIL import Image as PILImage  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    PILImage = None


@dataclass(slots=True)
class RasterImage:
    """Simple decoded raster representation used for fallback image operations."""

    width: int
    height: int
    pixels: list[tuple[int, int, int]]
    mode: str = "RGB"


class ImageLoader(Protocol):
    """Protocol for image loading services."""

    def load(self, source: str | Path) -> ImageFrame:
        """Load an image frame from a source path or identifier."""


class ImageService(Protocol):
    """Protocol for image utility services."""

    def save(self, image: ImageFrame, destination: str | Path) -> Path:
        """Save an image frame to disk."""

    def resize(self, image: ImageFrame, width: int, height: int) -> ImageFrame:
        """Resize an image to the supplied dimensions."""

    def rotate(self, image: ImageFrame, angle: float, *, expand: bool = True) -> ImageFrame:
        """Rotate an image by the supplied angle."""

    def crop(self, image: ImageFrame, left: int, top: int, right: int, bottom: int) -> ImageFrame:
        """Crop an image to the supplied bounds."""

    def convert_format(self, image: ImageFrame, target_format: str) -> ImageFrame:
        """Convert an image frame to the supplied format."""


class BaseImageLoader(ABC):
    """Abstract base class for image loading implementations."""

    def initialize(self) -> None:
        """Initialize the image loader."""

    def shutdown(self) -> None:
        """Shutdown the image loader."""

    @abstractmethod
    def load(self, source: str | Path) -> ImageFrame:
        """Load an image frame from a source path or identifier."""


class ImagePreprocessor(Protocol):
    """Protocol for image preprocessing services."""

    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Transform an image frame into a normalized representation."""


class BaseImagePreprocessor(ABC):
    """Abstract base class for image preprocessing implementations."""

    def initialize(self) -> None:
        """Initialize the preprocessor."""

    def shutdown(self) -> None:
        """Shutdown the preprocessor."""

    @abstractmethod
    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Transform the supplied image frame."""


class PassthroughImagePreprocessor(BaseImagePreprocessor):
    """A no-op preprocessor that leaves the image unchanged."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Image preprocessor constructed")

    def initialize(self) -> None:
        """Initialize the no-op preprocessor."""

        _emit_log(self._logger, "info", "Image preprocessor initialized")

    def shutdown(self) -> None:
        """Shutdown the no-op preprocessor."""

        _emit_log(self._logger, "info", "Image preprocessor shutdown")

    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Return the original image frame."""

        return image


class FileImageLoader(BaseImageLoader):
    """Image loader and utility service with Pillow and pure-Python fallbacks."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Image loader constructed")

    def initialize(self) -> None:
        """Initialize the image loader."""

        _emit_log(self._logger, "info", "Image loader initialized")

    def shutdown(self) -> None:
        """Shutdown the image loader."""

        _emit_log(self._logger, "info", "Image loader shutdown")

    def load(self, source: str | Path) -> ImageFrame:
        """Load an image frame from a filesystem path."""

        path = Path(source)
        data = path.read_bytes()
        image_format = self._detect_format(path=path, data=data)
        width, height, mode = self._inspect_dimensions(data=data, image_format=image_format)
        frame = ImageFrame(
            data=data,
            width=width,
            height=height,
            format=image_format,
            mode=mode,
            metadata={
                "source": str(path),
                "path": str(path),
                "size_bytes": len(data),
            },
        )
        _emit_log(
            self._logger,
            "info",
            "Image loaded",
            source=str(path),
            image_format=image_format,
            width=width,
            height=height,
        )
        return frame

    def save(self, image: ImageFrame, destination: str | Path) -> Path:
        """Save an image frame to disk."""

        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image.data)
        _emit_log(self._logger, "info", "Image saved", destination=str(path), image_format=image.format)
        return path

    def resize(self, image: ImageFrame, width: int, height: int) -> ImageFrame:
        """Resize an image to the supplied dimensions."""

        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive integers")

        if PILImage is not None:
            with PILImage.open(io.BytesIO(image.data)) as pil_image:
                resampling = getattr(getattr(PILImage, "Resampling", PILImage), "LANCZOS", 1)
                resized = pil_image.resize((width, height), resample=resampling)
                return self._pil_to_frame(resized, image_format=image.format, metadata=image.metadata)

        raster = self.decode(image)
        resized_pixels: list[tuple[int, int, int]] = []
        for y_index in range(height):
            source_y = min(raster.height - 1, int(y_index * raster.height / height))
            for x_index in range(width):
                source_x = min(raster.width - 1, int(x_index * raster.width / width))
                resized_pixels.append(raster.pixels[(source_y * raster.width) + source_x])
        return self.encode(
            RasterImage(width=width, height=height, pixels=resized_pixels, mode=raster.mode),
            image_format=image.format,
            metadata={**image.metadata, "operation": "resize"},
        )

    def rotate(self, image: ImageFrame, angle: float, *, expand: bool = True) -> ImageFrame:
        """Rotate an image by the supplied angle."""

        if PILImage is not None:
            with PILImage.open(io.BytesIO(image.data)) as pil_image:
                rotated = pil_image.rotate(angle, expand=expand)
                return self._pil_to_frame(rotated, image_format=image.format, metadata=image.metadata)

        normalized = int(angle) % 360
        raster = self.decode(image)
        if normalized == 0:
            return image
        if normalized not in {90, 180, 270}:
            raise RuntimeError("Fallback rotation only supports right-angle rotations without Pillow")

        if normalized == 180:
            pixels = list(reversed(raster.pixels))
            width = raster.width
            height = raster.height
        elif normalized == 90:
            width = raster.height
            height = raster.width
            pixels = []
            for y_index in range(height):
                for x_index in range(width):
                    source_x = y_index
                    source_y = raster.height - 1 - x_index
                    pixels.append(raster.pixels[(source_y * raster.width) + source_x])
        else:
            width = raster.height
            height = raster.width
            pixels = []
            for y_index in range(height):
                for x_index in range(width):
                    source_x = raster.width - 1 - y_index
                    source_y = x_index
                    pixels.append(raster.pixels[(source_y * raster.width) + source_x])

        return self.encode(
            RasterImage(width=width, height=height, pixels=pixels, mode=raster.mode),
            image_format=image.format,
            metadata={**image.metadata, "operation": "rotate", "angle": angle},
        )

    def crop(self, image: ImageFrame, left: int, top: int, right: int, bottom: int) -> ImageFrame:
        """Crop an image to the supplied bounds."""

        raster = self.decode(image)
        bounded_left = max(0, min(left, raster.width))
        bounded_top = max(0, min(top, raster.height))
        bounded_right = max(bounded_left, min(right, raster.width))
        bounded_bottom = max(bounded_top, min(bottom, raster.height))
        width = bounded_right - bounded_left
        height = bounded_bottom - bounded_top
        pixels: list[tuple[int, int, int]] = []
        for y_index in range(bounded_top, bounded_bottom):
            row_start = y_index * raster.width
            row = raster.pixels[row_start + bounded_left : row_start + bounded_right]
            pixels.extend(row)
        return self.encode(
            RasterImage(width=width, height=height, pixels=pixels, mode=raster.mode),
            image_format=image.format,
            metadata={**image.metadata, "operation": "crop"},
        )

    def convert_format(self, image: ImageFrame, target_format: str) -> ImageFrame:
        """Convert an image frame to the supplied format."""

        normalized_format = target_format.lower().lstrip(".")
        if normalized_format == image.format.lower():
            return ImageFrame(
                data=image.data,
                width=image.width,
                height=image.height,
                format=normalized_format,
                mode=image.mode,
                metadata=dict(image.metadata),
            )

        if PILImage is not None:
            with PILImage.open(io.BytesIO(image.data)) as pil_image:
                return self._pil_to_frame(pil_image, image_format=normalized_format, metadata=image.metadata)

        raster = self.decode(image)
        if normalized_format not in {"ppm", "pnm"}:
            raise RuntimeError("Format conversion requires Pillow for non-PPM targets")
        return self.encode(
            raster,
            image_format=normalized_format,
            metadata={**image.metadata, "operation": "convert_format"},
        )

    def decode(self, image: ImageFrame) -> RasterImage:
        """Decode an ``ImageFrame`` into a simple raster image."""

        if PILImage is not None:
            with PILImage.open(io.BytesIO(image.data)) as pil_image:
                rgb_image = pil_image.convert("RGB")
                return RasterImage(
                    width=rgb_image.width,
                    height=rgb_image.height,
                    pixels=list(rgb_image.getdata()),
                    mode="RGB",
                )

        image_format = image.format.lower()
        if image_format in {"ppm", "pnm"} or image.data.startswith(b"P6") or image.data.startswith(b"P3"):
            return self._decode_ppm(image.data)

        raise RuntimeError("Unable to decode image without Pillow support")

    def encode(
        self,
        raster: RasterImage,
        *,
        image_format: str = "ppm",
        metadata: dict[str, Any] | None = None,
    ) -> ImageFrame:
        """Encode a raster image into the shared ``ImageFrame`` payload."""

        normalized_format = image_format.lower()
        if PILImage is not None and normalized_format not in {"ppm", "pnm"}:
            pil_image = PILImage.new("RGB", (raster.width, raster.height))
            pil_image.putdata(raster.pixels)
            return self._pil_to_frame(pil_image, image_format=normalized_format, metadata=metadata)

        encoded = self._encode_ppm(raster)
        return ImageFrame(
            data=encoded,
            width=raster.width,
            height=raster.height,
            format="ppm",
            mode=raster.mode,
            metadata=dict(metadata or {}),
        )

    def _detect_format(self, *, path: Path, data: bytes) -> str:
        """Infer the image format from its content or path."""

        suffix = path.suffix.lower().lstrip(".")
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if data.startswith(b"\xff\xd8"):
            return "jpeg"
        if data.startswith((b"P6", b"P3")):
            return "ppm"
        if suffix:
            return suffix
        return "raw"

    def _inspect_dimensions(self, *, data: bytes, image_format: str) -> tuple[int | None, int | None, str]:
        """Read image dimensions without mutating the payload."""

        if PILImage is not None:
            try:
                with PILImage.open(io.BytesIO(data)) as pil_image:
                    return pil_image.width, pil_image.height, pil_image.mode
            except Exception as error:
                _emit_log(self._logger, "warning", "Image dimension inspection failed", error=str(error))

        if image_format in {"ppm", "pnm"} or data.startswith((b"P6", b"P3")):
            raster = self._decode_ppm(data)
            return raster.width, raster.height, raster.mode
        return None, None, "RGB"

    def _pil_to_frame(
        self,
        pil_image: Any,
        *,
        image_format: str,
        metadata: dict[str, Any] | None = None,
    ) -> ImageFrame:
        """Convert a Pillow image into the shared ``ImageFrame`` payload."""

        normalized_format = "jpeg" if image_format.lower() in {"jpg", "jpeg"} else image_format.lower()
        format_name = "JPEG" if normalized_format == "jpeg" else normalized_format.upper()
        buffer = io.BytesIO()
        save_image = pil_image.convert("RGB") if format_name in {"JPEG", "PPM"} else pil_image
        save_image.save(buffer, format=format_name)
        return ImageFrame(
            data=buffer.getvalue(),
            width=save_image.width,
            height=save_image.height,
            format=normalized_format,
            mode=getattr(save_image, "mode", "RGB"),
            metadata=dict(metadata or {}),
        )

    def _decode_ppm(self, data: bytes) -> RasterImage:
        """Decode a binary or plain-text PPM image."""

        token, offset = self._read_ppm_token(data, 0)
        if token not in {"P3", "P6"}:
            raise RuntimeError("Unsupported PPM header")
        width_token, offset = self._read_ppm_token(data, offset)
        height_token, offset = self._read_ppm_token(data, offset)
        max_value_token, offset = self._read_ppm_token(data, offset)
        width = int(width_token)
        height = int(height_token)
        max_value = int(max_value_token)
        if max_value <= 0:
            raise RuntimeError("Invalid PPM color depth")

        if token == "P6":
            while offset < len(data) and data[offset] in b" \t\r\n":
                offset += 1
            raw_pixels = data[offset:]
            expected = width * height * 3
            if len(raw_pixels) < expected:
                raise RuntimeError("PPM payload is truncated")
            pixels = [
                (
                    raw_pixels[index],
                    raw_pixels[index + 1],
                    raw_pixels[index + 2],
                )
                for index in range(0, expected, 3)
            ]
            return RasterImage(width=width, height=height, pixels=pixels)

        pixels: list[tuple[int, int, int]] = []
        expected_values = width * height * 3
        values: list[int] = []
        current_offset = offset
        while len(values) < expected_values:
            value_token, current_offset = self._read_ppm_token(data, current_offset)
            values.append(int(value_token))
        for index in range(0, expected_values, 3):
            pixels.append((values[index], values[index + 1], values[index + 2]))
        return RasterImage(width=width, height=height, pixels=pixels)

    @staticmethod
    def _read_ppm_token(data: bytes, offset: int) -> tuple[str, int]:
        """Read the next token from a PPM payload."""

        length = len(data)
        while offset < length:
            byte = data[offset]
            if byte == 35:  # '#'
                while offset < length and data[offset] not in b"\r\n":
                    offset += 1
            elif byte in b" \t\r\n":
                offset += 1
            else:
                break

        start = offset
        while offset < length and data[offset] not in b" \t\r\n#":
            offset += 1
        return data[start:offset].decode("ascii"), offset

    @staticmethod
    def _encode_ppm(raster: RasterImage) -> bytes:
        """Encode a raster image as a binary PPM payload."""

        header = f"P6\n{raster.width} {raster.height}\n255\n".encode("ascii")
        pixel_bytes = bytearray()
        for red, green, blue in raster.pixels:
            pixel_bytes.extend((red, green, blue))
        return header + bytes(pixel_bytes)


__all__ = [
    "BaseImageLoader",
    "BaseImagePreprocessor",
    "FileImageLoader",
    "ImageLoader",
    "ImagePreprocessor",
    "ImageService",
    "PassthroughImagePreprocessor",
    "RasterImage",
]

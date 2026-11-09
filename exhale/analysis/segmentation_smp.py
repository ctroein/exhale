"""Lazy SMP ResNet18 U-Net inference with the supplied XRF-trained checkpoint."""

from functools import lru_cache
from pathlib import Path

from .segmentation_monai import segment_unet


@lru_cache(maxsize=1)
def _model(filename: str, modified_ns: int, device: str):
    """Load complete trained weights without acquiring ImageNet encoder weights."""
    import segmentation_models_pytorch as smp
    import torch

    checkpoint = torch.load(filename, map_location="cpu", weights_only=True)
    if checkpoint.get("encoder") != "resnet18":
        raise ValueError("SMP U-Net requires the ResNet18 XRF checkpoint")
    patch_size = checkpoint.get("patch_size")
    if type(patch_size) is not int or patch_size < 32 or patch_size % 32:
        raise ValueError("Invalid SMP U-Net checkpoint patch size")

    class SMPUNet(torch.nn.Module):
        """Repeat the grayscale input and apply the training's ImageNet normalization."""

        def __init__(self):
            super().__init__()
            self.network = smp.Unet(
                encoder_name="resnet18",
                encoder_weights=None,
                in_channels=3,
                classes=3,
                activation=None,
                decoder_channels=(128, 64, 32, 16, 16),
            )
            self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
            self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

        def forward(self, images):
            return self.network((images.repeat(1, 3, 1, 1) - self.mean) / self.std)

    model = SMPUNet()
    model.load_state_dict(checkpoint["model"], strict=True)
    return model.to(device).eval(), patch_size


def segment_smp(
    image, *, model_path, seed_threshold=0.5, min_size=20, callback=lambda _message: None
):
    """Infer original-size instances using shared U-Net tiling and watershed."""
    path = Path(model_path).expanduser()
    if not model_path or not path.is_file():
        raise ValueError("The SMP U-Net trained model is unavailable")
    return segment_unet(
        image,
        model_loader=lambda device: _model(str(path.resolve()), path.stat().st_mtime_ns, device),
        name="SMP U-Net",
        seed_threshold=seed_threshold,
        min_size=min_size,
        callback=callback,
    )

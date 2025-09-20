# GenerateTextures.py
# repo root: RemadeTextures/ and DolphinTextureExtractionTool/ expected here

import os
import shutil
import subprocess
import tempfile
import configparser
import sys

# ---------- CONFIG ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_ROOT = os.path.join(BASE_DIR, "RemadeTextures")
OUTPUT_ROOT = os.path.join(BASE_DIR, "GeneratedTextures")
TOOL_FOLDER = os.path.join(BASE_DIR, "DolphinTextureExtractionTool")

APPLY_MAPPING_TO_WII = False   # if True, Wii outputs will be renamed to mapping base
APPLY_OPACITY = True           # True to apply 50% alpha ONCE before splitting
# ----------------------------

# Conditionally import Pillow only if opacity is enabled
if APPLY_OPACITY:
    try:
        from PIL import Image
    except Exception:
        print("Pillow is required to apply opacity. Install with: python -m pip install pillow")
        sys.exit(1)

def find_tool_exe(folder):
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Tool folder missing: {folder}")
    exes = [f for f in os.listdir(folder) if f.lower().endswith('.exe')]
    if not exes:
        raise FileNotFoundError("No .exe found in DolphinTextureExtractionTool folder.")
    for e in exes:
        if e.lower().startswith("dolphintextureextraction"):
            return os.path.join(folder, e)
    return os.path.join(folder, exes[0])

def read_mappings(path):
    m = {}
    if not os.path.isfile(path):
        return m
    cfg = configparser.ConfigParser()
    cfg.read(path)
    if 'Mappings' in cfg:
        for k, v in cfg.items('Mappings'):
            key = k.strip().lower()
            val = v.strip()
            val = os.path.splitext(val)[0]
            if key:
                m[key] = val
    return m

def unique_dest(dest_dir, filename):
    base, ext = os.path.splitext(filename)
    candidate = filename
    i = 1
    full = os.path.join(dest_dir, candidate)
    while os.path.exists(full):
        candidate = f"{base}_{i}{ext}"
        full = os.path.join(dest_dir, candidate)
        i += 1
    return full

def apply_half_opacity(path):
    """Make alpha 50% if opacity mode is enabled. No-op when disabled."""
    if not APPLY_OPACITY:
        return
    try:
        im = Image.open(path).convert("RGBA")
        r, g, b, a = im.split()
        a = a.point(lambda i: int(i * 0.5))  # multiply alpha by 0.5
        im = Image.merge("RGBA", (r, g, b, a))
        im.save(path)
    except Exception as e:
        print(f"  [WARN] opacity failed for {path}: {e}")

def gather_pngs(folder):
    out = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith('.png'):
                out.append(os.path.join(root, f))
    return out

def ensure_clean_output(root):
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(root, exist_ok=True)
    w = os.path.join(root, "Wii")
    p = os.path.join(root, "PS2")
    os.makedirs(w, exist_ok=True)
    os.makedirs(p, exist_ok=True)
    return w, p

def run_splitter_single(tool_exe, src_file, out_dir):
    cmd = [tool_exe, 'z', src_file, out_dir, '-p:bar']
    subprocess.run(cmd, check=True)

def main():
    tool_exe = find_tool_exe(TOOL_FOLDER)
    mappings = read_mappings(os.path.join(BASE_DIR, "Mappings.ini"))
    print("Tool:", tool_exe)
    print("Loaded mappings:", len(mappings))
    print("APPLY_OPACITY =", APPLY_OPACITY, "APPLY_MAPPING_TO_WII =", APPLY_MAPPING_TO_WII)

    wii_root, ps2_root = ensure_clean_output(OUTPUT_ROOT)

    processed = 0
    skipped = 0

    # Walk input tree
    for dirpath, _, filenames in os.walk(INPUT_ROOT):
        rel_dir = os.path.relpath(dirpath, INPUT_ROOT)
        if rel_dir == ".":
            rel_dir = ""
        wii_sub = os.path.join(wii_root, rel_dir)
        ps2_sub = os.path.join(ps2_root, rel_dir)
        os.makedirs(wii_sub, exist_ok=True)
        os.makedirs(ps2_sub, exist_ok=True)

        for fname in filenames:
            if not fname.lower().endswith('.png'):
                skipped += 1
                continue

            src_path = os.path.join(dirpath, fname)
            base_key = os.path.splitext(fname)[0].lower()

            # === Create a temp directory that *keeps the original basename* ===
            temp_src_dir = tempfile.mkdtemp(prefix="dte_src_")
            try:
                temp_src_path = os.path.join(temp_src_dir, fname)
                shutil.copy2(src_path, temp_src_path)

                # Apply opacity to the temp copy BEFORE splitting
                apply_half_opacity(temp_src_path)

                # 1) Copy the modified temp file into PS2 mirrored folder
                ps2_dest_path = unique_dest(ps2_sub, fname)
                shutil.copy2(temp_src_path, ps2_dest_path)

                # 2) Run splitter on the temp file (filename preserved)
                temp_out = tempfile.mkdtemp(prefix="dte_out_")
                try:
                    run_splitter_single(tool_exe, temp_src_path, temp_out)
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] splitter failed for {src_path}: {e}")
                    shutil.rmtree(temp_out, ignore_errors=True)
                    # cleanup temp_src_dir and continue to next file
                    continue

                # 3) Move only produced PNGs from temp_out to Wii mirror (no more opacity touches)
                new_pngs = gather_pngs(temp_out)
                moved_names = []
                if not new_pngs:
                    print(f"  [WARN] splitter produced no PNGs for {src_path}")
                else:
                    for png_path in new_pngs:
                        png_name = os.path.basename(png_path)
                        # optionally apply mapping to Wii outputs
                        if APPLY_MAPPING_TO_WII and base_key in mappings:
                            dest_base = mappings[base_key]
                            dest_name = dest_base + os.path.splitext(png_name)[1]
                        else:
                            dest_name = png_name
                        dest_full = unique_dest(wii_sub, dest_name)
                        shutil.move(png_path, dest_full)
                        moved_names.append(os.path.basename(dest_full))

                # cleanup splitter temp out dir
                shutil.rmtree(temp_out, ignore_errors=True)

                # 4) Rename PS2 copy now if mapping exists (map keys without .png)
                if base_key in mappings:
                    mapped_base = mappings[base_key]
                    mapped_name = mapped_base + ".png"
                    mapped_full = unique_dest(ps2_sub, mapped_name)
                    try:
                        os.replace(ps2_dest_path, mapped_full)
                        ps2_dest_path = mapped_full
                    except Exception as e:
                        print(f"  [WARN] could not rename PS2 file {ps2_dest_path} -> {mapped_full}: {e}")

                processed += 1
                print(f"Processed: {os.path.join(rel_dir, fname)} -> PS2:{os.path.basename(ps2_dest_path)} + Wii:{', '.join(moved_names) if moved_names else 'none'}")

            finally:
                # always remove the temp source directory (and its files)
                shutil.rmtree(temp_src_dir, ignore_errors=True)

    print("Finished.")
    print(f"Processed: {processed}, Skipped non-png: {skipped}")
    print("Output root:", OUTPUT_ROOT)
    print("  Wii root:", wii_root)
    print("  PS2 root:", ps2_root)

if __name__ == "__main__":
    main()

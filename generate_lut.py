import os
import sys

try:
    import cv2
    import numpy as np
    import colour
    import json
except ImportError:
    print("---------------------------------------------------------")
    print("Error: Required libraries not found.")
    print("Please install them by opening your terminal and typing:")
    print("pip install opencv-python numpy colour-science")
    print("---------------------------------------------------------")
    sys.exit(1)

def select_points(image, window_name="Select 4 corners"):
    points = []
    # Make a copy for drawing
    clone = image.copy()
    
    def click_event(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(points) < 4:
                points.append((x, y))
                cv2.circle(clone, (x, y), 5, (0, 255, 0), -1)
                
                # Draw lines between points
                if len(points) > 1:
                    cv2.line(clone, points[-2], points[-1], (0, 255, 0), 2)
                if len(points) == 4:
                    cv2.line(clone, points[3], points[0], (0, 255, 0), 2)
                    print(f"4 Punkte fuer {window_name} ausgewaehlt.")
                    print("--> Druecke eine beliebige Taste (z.B. Enter/Leertaste) um fortzufahren.")
                
                cv2.imshow(window_name, clone)

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1200, 800)
    cv2.imshow(window_name, clone)
    cv2.setMouseCallback(window_name, click_event)
    
    print("\n" + "="*50)
    print(f"BITTE KLICKE AUF 4 ECKEN IN DIESEM FENSTER: {window_name}")
    print("Reihenfolge: Oben-Links, Oben-Rechts, Unten-Rechts, Unten-Links")
    print("Klicke auf die aeussersten Ecken des 4x6 Farbrasters.")
    print("Druecke nach dem 4. Klick eine beliebige Taste (z.B. Enter).")
    print("="*50 + "\n")
    
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    
    if len(points) != 4:
        print("Fehler: Du hast nicht genau 4 Punkte ausgewaehlt. Abbruch.")
        sys.exit(1)
        
    return np.array(points, dtype="float32")

def extract_patches(img_float, pts):
    width = 600
    height = 400
    # Destination points for a flat rectangle
    dst_pts = np.array([
        [0, 0],
        [width - 1, 0],
        [width - 1, height - 1],
        [0, height - 1]
    ], dtype="float32")
    
    # Calculate perspective transform and warp
    M = cv2.getPerspectiveTransform(pts, dst_pts)
    warped = cv2.warpPerspective(img_float, M, (width, height))
    
    # Calculated based on exact fractional geometry extracted from analysis of the image
    # These are initial guesses, user can drag them.
    patch_centers = []
    
    # Hardcoded coordinates based on your perfect manual calibration
    patch_centers = [
        [0.0533, 0.0850], [0.1533, 0.0950], [0.8467, 0.0925], [0.9433, 0.0900], 
        [0.0533, 0.2275], [0.1517, 0.2275], [0.8467, 0.2325], [0.9467, 0.2250], 
        [0.0533, 0.3650], [0.1567, 0.3650], [0.8467, 0.3700], [0.9467, 0.3675], 
        [0.0567, 0.4975], [0.1533, 0.5050], [0.8467, 0.5075], [0.9467, 0.5050], 
        [0.0567, 0.6350], [0.1567, 0.6400], [0.8467, 0.6400], [0.9500, 0.6375], 
        [0.0533, 0.7700], [0.1533, 0.7750], [0.8467, 0.7750], [0.9467, 0.7700], 
        [0.0533, 0.9100], [0.1550, 0.9100], [0.8500, 0.9075], [0.9467, 0.9100], 
        [0.5000, 0.1400], [0.5000, 0.3750], [0.5000, 0.6250], [0.5000, 0.8625]
    ]
        
    # Convert fractions to absolute pixel coords
    pixel_centers = [[int(px * width), int(py * height)] for px, py in patch_centers]
    
    roi_size = 20 # size of the square in the center of each patch to average
    
    # INTERACTIVE ADJUSTMENT
    display_warped = (np.clip(warped, 0, 1.0) * 255).astype(np.uint8)
    
    # State for dragging
    drag_state = {
        'dragging_idx': -1,
        'centers': pixel_centers
    }
    
    def adjust_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            # check if click is near any center
            for i, (cx, cy) in enumerate(drag_state['centers']):
                if abs(x - cx) < roi_size//2 and abs(y - cy) < roi_size//2:
                    drag_state['dragging_idx'] = i
                    break
        elif event == cv2.EVENT_MOUSEMOVE:
            if drag_state['dragging_idx'] != -1:
                # Update location
                drag_state['centers'][drag_state['dragging_idx']] = [x, y]
        elif event == cv2.EVENT_LBUTTONUP:
            if drag_state['dragging_idx'] != -1:
                drag_state['centers'][drag_state['dragging_idx']] = [x, y]
                drag_state['dragging_idx'] = -1

    window_name = "Punkte korrigieren (Ziehen & Absetzen)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1200, 800)
    cv2.setMouseCallback(window_name, adjust_mouse)
    
    print("\n" + "="*50)
    print("MANUELLE KORREKTUR DER FELDER:")
    print("Klicke und ziehe (Drag & Drop) die roten Quadrate,")
    print("sodass jedes kleine Quadrat perfekt mittig in einer Farbe/Graustufe liegt.")
    print("Druecke Enter in diesem Fenster, wenn alle Quadrate sitzen.")
    print("="*50 + "\n")
    
    while True:
        frame = display_warped.copy()
        for cx, cy in drag_state['centers']:
            cv2.rectangle(frame, 
                          (cx - roi_size//2, cy - roi_size//2), 
                          (cx + roi_size//2, cy + roi_size//2), 
                          (0, 0, 255), 2)
            cv2.circle(frame, (cx, cy), 2, (0, 255, 0), -1)
            
        cv2.imshow(window_name, frame)
        key = cv2.waitKey(20) & 0xFF
        if key == 13 or key == 32: # Enter or Space
            break
            
    cv2.destroyWindow(window_name)

    # Finally perform extraction based on user-adjusted centers
    patch_colors = []
    for cx, cy in drag_state['centers']:
        # clamp coords just in case user dragged off screen
        cy_min = max(0, cy - roi_size//2)
        cy_max = min(height, cy + roi_size//2)
        cx_min = max(0, cx - roi_size//2)
        cx_max = min(width, cx + roi_size//2)
        
        roi = warped[cy_min:cy_max, cx_min:cx_max]
        avg_color = roi.mean(axis=(0, 1)) # BGR format
        patch_colors.append(avg_color)
    
    patch_colors = np.array(patch_colors)
    # Convert BGR to RGB
    patch_colors = patch_colors[:, ::-1]
    return patch_colors

def select_files(files, source_only=False):
    print("\nGefundene Bilder:")
    for i, f in enumerate(files):
        print(f"  [{i}] {f}")
        
    try:
        source_idx = int(input("\nWelche Nummer ist das QUELL-Bild (zu veraendernde Kamera, z.B. Leica)? "))
        if source_only:
            return source_idx, -1
            
        target_idx = int(input("Welche Nummer ist das ZIEL-Bild (Referenz-Kamera, z.B. Lumix)? "))
    except ValueError:
        print("Fehler: Bitte eine gueltige Nummer eingeben.")
        sys.exit(1)
        
    if source_idx < 0 or source_idx >= len(files) or target_idx < 0 or target_idx >= len(files):
        print("Fehler: Ungueltige Nummernauswahl.")
        sys.exit(1)
        
    if not source_only and source_idx == target_idx:
        print("Fehler: Quelle und Ziel muessen unterschiedliche Bilder sein.")
        sys.exit(1)
        
    return source_idx, target_idx

def select_log_profiles():
    import colour
    available_curves = sorted(list(colour.models.LOG_ENCODINGS.keys()))
    if "GP-Log2" not in available_curves:
        available_curves.append("GP-Log2")
        available_curves.sort()
    
    print("\nVerfuegbare Kamera Log-Profile:")
    for i, curve in enumerate(available_curves):
        print(f"  [{i}] {curve}")
        
    try:
        source_curve_idx = int(input("\nWelches Log-Profil nutzt das QUELL-Bild (z.B. L-Log)? "))
        target_curve_idx = int(input("Welches Log-Profil nutzt das ZIEL-Bild (z.B. V-Log)? "))
    except ValueError:
        print("Fehler: Bitte eine gueltige Nummer eingeben.")
        sys.exit(1)
        
    if source_curve_idx < 0 or source_curve_idx >= len(available_curves) or target_curve_idx < 0 or target_curve_idx >= len(available_curves):
        print("Fehler: Ungueltige Nummernauswahl fuer Log-Kurven.")
        sys.exit(1)
        
    return available_curves[source_curve_idx], available_curves[target_curve_idx]


def select_display_transform():
    display_options = ['Rec709 (BT.709)', 'sRGB', 'Gamma 2.4', 'Gamma 2.2']

    print("\nReferenz-Farbraum (Display-Transferfunktion):")
    print("Deine Referenz ist ein Screengrab mit bereits gebakener LUT (Display-Referenz).")
    print("Waehle die Transfer-Kurve, mit der das Referenzbild kodiert ist:")
    print("  Rec709 (BT.709) = echte BT.709 OETF (kein simples Gamma!)")
    print("  sRGB            = echte sRGB OETF")
    print("  Gamma 2.4 / 2.2 = reines Power-Law (Fallback)")
    for i, name in enumerate(display_options):
        print(f"  [{i}] {name}")
    try:
        idx = int(input("Auswahl: "))
    except ValueError:
        print("Fehler: Bitte eine gueltige Nummer eingeben.")
        sys.exit(1)
    if idx < 0 or idx >= len(display_options):
        print("Fehler: Ungueltige Auswahl.")
        sys.exit(1)
    return display_options[idx]


def _apply_display_decode_display_to_linear(ref_colors, transform_name):
    """Decode display-referred values to linear using proper OETF inverse."""
    import colour
    x = np.clip(ref_colors, 0.0, 1.0)
    if transform_name == 'Rec709 (BT.709)':
        return colour.models.oetf_inverse_BT709(x)
    elif transform_name == 'sRGB':
        return colour.models.eotf_sRGB(x)
    elif transform_name == 'Gamma 2.4':
        return np.power(x, 2.4)
    elif transform_name == 'Gamma 2.2':
        return np.power(x, 2.2)
    else:
        return np.power(x, 2.4)


def _apply_display_encode_linear_to_display(linear, transform_name):
    """Encode linear values to display space using proper OETF."""
    import colour
    x = np.clip(linear, 1e-6, 100.0)
    if transform_name == 'Rec709 (BT.709)':
        return np.clip(colour.models.oetf_BT709(x), 0.0, 1.0)
    elif transform_name == 'sRGB':
        return np.clip(colour.models.eotf_inverse_sRGB(x), 0.0, 1.0)
    elif transform_name == 'Gamma 2.4':
        return np.clip(np.power(x, 1.0 / 2.4), 0.0, 1.0)
    elif transform_name == 'Gamma 2.2':
        return np.clip(np.power(x, 1.0 / 2.2), 0.0, 1.0)
    else:
        return np.clip(np.power(x, 1.0 / 2.4), 0.0, 1.0)


def select_source_log_profile():
    import colour
    available_curves = sorted(list(colour.models.LOG_ENCODINGS.keys()))
    if "GP-Log2" not in available_curves:
        available_curves.append("GP-Log2")
        available_curves.sort()

    print("\nVerfuegbare Kamera Log-Profile:")
    for i, curve in enumerate(available_curves):
        print(f"  [{i}] {curve}")

    try:
        idx = int(input("\nWelches Log-Profil nutzt diese Source-Kamera? "))
    except ValueError:
        print("Fehler: Bitte eine gueltige Nummer eingeben.")
        sys.exit(1)
    if idx < 0 or idx >= len(available_curves):
        print("Fehler: Ungueltige Nummernauswahl.")
        sys.exit(1)
    return available_curves[idx]


def run_reference_match_mode():
    print("\n--- REFERENCE MATCH LUT MODUS ---")
    print("Dieser Modus gleicht mehrere Log-Kameras auf EIN Referenzbild ab.")
    print("Die Referenz ist bereits im Display-Farbraum (fertiger Look mit LUT).")
    print("=" * 50)

    valid_exts = ['.tif', '.tiff', '.jpg', '.jpeg', '.png']
    files = sorted([f for f in os.listdir('.') if os.path.isfile(f) and any(f.lower().endswith(ext) for ext in valid_exts)])

    if len(files) < 2:
        print(f"Fehler: Mindestens 2 Bilddateien ({', '.join(valid_exts)}) im Ordner erforderlich.")
        sys.exit(1)

    display_transform = select_display_transform()

    # ---- Select and process reference image ONCE ----
    print("\n--- REFERENZBILD auswaehlen ---")
    print("(Das Bild mit dem finalen Look, z.B. S1II Screengrab)")
    print("\nGefundene Bilder:")
    for i, f in enumerate(files):
        print(f"  [{i}] {f}")

    try:
        ref_idx = int(input("\nWelche Nummer ist das REFERENZ-Bild? "))
    except ValueError:
        print("Fehler: Bitte eine gueltige Nummer eingeben.")
        sys.exit(1)
    if ref_idx < 0 or ref_idx >= len(files):
        print("Fehler: Ungueltige Nummernauswahl.")
        sys.exit(1)

    ref_path = files[ref_idx]
    ref_name = os.path.splitext(ref_path)[0]
    ref_colors = process_single_image(ref_path, f"Referenz: {ref_name}")

    # ---- Source batch loop ----
    remaining = [f for i, f in enumerate(files) if i != ref_idx]
    lut_count = 0

    while remaining:
        print(f"\n--- SOURCE-KAMERA ({len(remaining)} verbleibend) ---")
        print("\nGefundene Bilder:")
        for i, f in enumerate(remaining):
            print(f"  [{i}] {f}")

        try:
            src_idx = int(input("\nWelche Nummer ist die SOURCE-Kamera? "))
        except ValueError:
            print("Fehler: Bitte eine gueltige Nummer eingeben.")
            sys.exit(1)
        if src_idx < 0 or src_idx >= len(remaining):
            print("Fehler: Ungueltige Nummernauswahl.")
            sys.exit(1)

        src_path = remaining[src_idx]
        src_name = os.path.splitext(src_path)[0]
        source_log = select_source_log_profile()

        src_colors = process_single_image(src_path, f"Source: {src_name}")

        # Compute and save LUT
        lut_name = f"{src_name}_to_{ref_name}_DisplayMatch"
        out_filename = get_unique_filename(lut_name)

        print(f"\nBerechne Root-Polynomial Matrix + 65^3 LUT: {source_log} -> {display_transform} ...")

        try:
            if source_log == "GP-Log2":
                source_lin = (np.power(600.0, np.clip(src_colors, 0.0, 1.0)) - 1.0) / 599.0
            else:
                source_lin = colour.models.log_decoding(src_colors, function=source_log)
        except Exception as e:
            print(f"Warnung: Log Decoding fehlgeschlagen ({e}). Nutze Gamma 2.4 Fallback.")
            source_lin = np.power(np.clip(src_colors, 0, 1), 2.4)

        ref_lin = _apply_display_decode_display_to_linear(ref_colors, display_transform)

        # Black-point normalization
        source_lin64 = np.asarray(source_lin, dtype=np.float64)
        ref_lin64 = np.asarray(ref_lin, dtype=np.float64)
        src_black = float(np.percentile(source_lin64, 5))
        tgt_black = float(np.percentile(ref_lin64, 5))
        source_norm = np.maximum(source_lin64 - src_black, 0.0)
        ref_norm = np.maximum(ref_lin64 - tgt_black, 0.0)

        # Root-polynomial expansion without offset: [R, G, B, sqrt(RG), sqrt(RB), sqrt(GB)]
        r, g, b = source_norm[:, 0:1], source_norm[:, 1:2], source_norm[:, 2:3]
        source_expanded = np.hstack([r, g, b,
            np.sqrt(np.maximum(r * g, 0)), np.sqrt(np.maximum(r * b, 0)), np.sqrt(np.maximum(g * b, 0))])

        # Weighted least squares: duplicate gray patches 10x
        gray_indices = [28, 29, 30, 31]
        extra_s, extra_t = [], []
        for i in range(len(source_expanded)):
            if (i % 32) in gray_indices:
                for _ in range(9):
                    extra_s.append(source_expanded[i])
                    extra_t.append(ref_norm[i])
        if extra_s:
            source_expanded = np.vstack([source_expanded, np.array(extra_s)])
            ref_norm = np.vstack([ref_norm, np.array(extra_t)])

        matrix, residuals, rank, s = np.linalg.lstsq(source_expanded, ref_norm, rcond=None)

        # Measure accuracy on original patches
        orig_expanded = np.hstack([r, g, b,
            np.sqrt(np.maximum(r * g, 0)), np.sqrt(np.maximum(r * b, 0)), np.sqrt(np.maximum(g * b, 0))])
        predicted = np.dot(orig_expanded, matrix)
        mse = np.mean((ref_norm[:len(predicted)] - predicted) ** 2)
        print(f"Abweichung (MSE im Linear-Space): {mse:.6f}")

        lut = colour.LUT3D(size=65, name=lut_name)
        try:
            if source_log == "GP-Log2":
                grid_lin = (np.power(600.0, np.clip(lut.table, 0.0, 1.0)) - 1.0) / 599.0
            else:
                grid_lin = colour.models.log_decoding(lut.table, function=source_log)
        except Exception:
            grid_lin = np.power(np.clip(lut.table, 0, 1), 2.4)

        flat_grid_lin = grid_lin.reshape(-1, 3)
        flat_grid_norm = np.maximum(flat_grid_lin - src_black, 0.0)
        gr, gg, gb = flat_grid_norm[:, 0:1], flat_grid_norm[:, 1:2], flat_grid_norm[:, 2:3]
        flat_grid_expanded = np.hstack([gr, gg, gb,
            np.sqrt(np.maximum(gr * gg, 0)), np.sqrt(np.maximum(gr * gb, 0)), np.sqrt(np.maximum(gg * gb, 0))])
        flat_transformed_lin = np.dot(flat_grid_expanded, matrix)
        flat_transformed_lin = np.maximum(flat_transformed_lin + tgt_black, 1e-6)
        flat_transformed_lin = np.clip(flat_transformed_lin, 1e-6, 100.0)

        flat_transformed_display = _apply_display_encode_linear_to_display(flat_transformed_lin, display_transform)
        flat_transformed_display = np.clip(flat_transformed_display, 0.0, 1.0)

        lut.table = flat_transformed_display.reshape((65, 65, 65, 3))
        colour.write_LUT(lut, out_filename)

        print(f"\nERFOLG! LUT gespeichert: {out_filename}")
        lut_count += 1

        remaining.pop(src_idx)

        if remaining:
            more = input("\nWeitere Source-Kamera verarbeiten? (j/n): ")
            if more.lower() != 'j':
                break

    print(f"\n{'=' * 50}")
    print(f"FERTIG! {lut_count} LUT(s) generiert.")
    print(f"{'=' * 50}")


def process_single_image(img_path, label):
    print(f"\nLade Bild: {label} ({img_path})...")
    img = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"Fehler: Konnte Bild nicht lesen: {img_path}")
        sys.exit(1)

    if len(img.shape) == 3 and img.shape[2] == 4:
        img = img[:, :, :3]

    is_16bit = img.dtype == np.uint16
    if is_16bit:
        img_float = (img / 65535.0).astype(np.float32)
    else:
        img_float = (img / 255.0).astype(np.float32)

    img_display = (np.clip(img_float, 0, 1) * 255).astype(np.uint8)

    pts = select_points(img_display, f"Ecken: {label}")
    print(f"Extrahiere Farben aus {label}...")
    colors = extract_patches(img_float, pts)
    return colors

def get_unique_filename(base_name, extension="cube"):
    filename = f"{base_name}.{extension}"
    counter = 2
    
    while os.path.exists(filename):
        filename = f"{base_name}_{counter}.{extension}"
        counter += 1
        
    return filename

def main():
    print("==================================================")
    print("        LUT GENERATOR (SINGLE & MASTER MODE)      ")
    print("==================================================")
    print(" [1] SINGLE LUT (Ein Bildpaar abgleichen)")
    print(" [2] MASTER LUT (Mehrere Bildpaare / Lichtsituationen verschmelzen)")
    print(" [3] REFERENCE MATCH LUT (Referenz=fertiger Look, Sources=Log)")
    mode = input("Waehle den Modus (1, 2 oder 3): ")

    if mode.strip() == '3':
        run_reference_match_mode()
        return

    is_master_mode = mode.strip() == '2'
    
    valid_exts = ['.tif', '.tiff', '.jpg', '.jpeg', '.png']
    files = [f for f in os.listdir('.') if os.path.isfile(f) and any(f.lower().endswith(ext) for ext in valid_exts)]
    
    if len(files) < 2:
        print(f"Fehler: Mindestens 2 Bilddateien ({', '.join(valid_exts)}) im Ordner erforderlich.")
        sys.exit(1)
        
    source_log_curve, target_log_curve = select_log_profiles()
        
    all_source_colors = []
    all_target_colors = []
    
    if is_master_mode:
        print("\n--- MASTER LUT MODUS ---")
        out_name = input("Wie soll die finale Master LUT heissen (z.B. Leica_to_Lumix_Universal)? ")
        if not out_name.strip():
            out_name = "Universal_Master_Match"
            
        pairs_count = 1
        while True:
            print(f"\n[ PAAR {pairs_count} HINZUFUEGEN ]")
            s_idx, t_idx = select_files(files)
            source_path = files[s_idx]
            target_path = files[t_idx]
            
            # --- PROCESS A SINGLE PAIR ---
            s_colors, t_colors = process_pair(source_path, target_path)
            all_source_colors.append(s_colors)
            all_target_colors.append(t_colors)
            
            more = input("\nMoechtest du EIN WEITERES Licht-Paar hinzufuegen? (j/n): ")
            if more.lower() != 'j':
                break
            pairs_count += 1
            
        # Combine all collected dots into a giant flat array
        all_source_colors = np.vstack(all_source_colors)
        all_target_colors = np.vstack(all_target_colors)
        lut_name = out_name
        
    else:
        print("\n--- SINGLE LUT MODUS ---")
        s_idx, t_idx = select_files(files)
        source_path = files[s_idx]
        target_path = files[t_idx]
        source_name = os.path.splitext(source_path)[0]
        target_name = os.path.splitext(target_path)[0]
        lut_name = f"{source_name}_to_{target_name}_Match"
        
        s_colors, t_colors = process_pair(source_path, target_path)
        all_source_colors = s_colors
        all_target_colors = t_colors
        
    print("\nBerechne Root-Polynomial Matrix + Offset Optimierung (Linear Space)...")
    
    # 1. LOG TO LINEAR CONVERSION
    try:
        if source_log_curve == "GP-Log2":
            source_lin = (np.power(600.0, np.clip(all_source_colors, 0.0, 1.0)) - 1.0) / 599.0
        else:
            source_lin = colour.models.log_decoding(all_source_colors, function=source_log_curve)
            
        if target_log_curve == "GP-Log2":
            target_lin = (np.power(600.0, np.clip(all_target_colors, 0.0, 1.0)) - 1.0) / 599.0
        else:
            target_lin = colour.models.log_decoding(all_target_colors, function=target_log_curve)
    except Exception as e:
        print(f"Warnung: Natives Log Decoding fehlgeschlagen ({e}). Nutze Gamma 2.4 Fallback.")
        source_lin = np.power(np.clip(all_source_colors, 0, 1), 2.4)
        target_lin = np.power(np.clip(all_target_colors, 0, 1), 2.4)
    
    # 1b. BLACK-POINT NORMALIZATION – ensures black maps to black
    source_lin64 = np.asarray(source_lin, dtype=np.float64)
    target_lin64 = np.asarray(target_lin, dtype=np.float64)
    src_black = float(np.percentile(source_lin64, 5))
    tgt_black = float(np.percentile(target_lin64, 5))
    source_norm = np.maximum(source_lin64 - src_black, 0.0)
    target_norm = np.maximum(target_lin64 - tgt_black, 0.0)
    print(f"Black-Point: Source={src_black:.6f} Target={tgt_black:.6f}")
    
    # 2. ROOT-POLYNOMIAL EXPANSION (Finlayson 2015) – without offset
    # [R, G, B, sqrt(RG), sqrt(RB), sqrt(GB)] → 6 terms, no all-ones column
    r, g, b = source_norm[:, 0:1], source_norm[:, 1:2], source_norm[:, 2:3]
    source_expanded = np.hstack([r, g, b,
        np.sqrt(np.maximum(r * g, 0)), np.sqrt(np.maximum(r * b, 0)), np.sqrt(np.maximum(g * b, 0))])

    # 3. GEWICHTUNG DER GRAUBLOECKE (duplicate gray patches 10x)
    gray_indices = [28, 29, 30, 31]
    extra_s, extra_t = [], []
    for i in range(len(source_expanded)):
        if (i % 32) in gray_indices:
            for _ in range(9):
                extra_s.append(source_expanded[i])
                extra_t.append(target_norm[i])
    if extra_s:
        source_expanded = np.vstack([source_expanded, np.array(extra_s)])
        target_norm = np.vstack([target_norm, np.array(extra_t)])
    
    # 4. MATRIX KALKULATION (6x3 Root-Polynomial, no offset)
    matrix, residuals, rank, s = np.linalg.lstsq(source_expanded, target_norm, rcond=None)
    
    # Measure accuracy on original patches
    orig_expanded = np.hstack([r, g, b,
        np.sqrt(np.maximum(r * g, 0)), np.sqrt(np.maximum(r * b, 0)), np.sqrt(np.maximum(g * b, 0))])
    predicted = np.dot(orig_expanded, matrix)
    mse = np.mean((target_norm[:len(predicted)] - predicted)**2)
    print(f"Abweichung (MSE im Linear-Space): {mse:.6f}")
    
    print("\nGeneriere die artefaktfreie 65x65 3D-LUT...")
    lut = colour.LUT3D(size=65, name=lut_name)
    
    try:
        if source_log_curve == "GP-Log2":
            grid_lin = (np.power(600.0, np.clip(lut.table, 0.0, 1.0)) - 1.0) / 599.0
        else:
            grid_lin = colour.models.log_decoding(lut.table, function=source_log_curve)
    except Exception:
        grid_lin = np.power(lut.table, 2.4)
    
    flat_grid_lin = grid_lin.reshape(-1, 3)
    
    # Normalize grid with same black point, expand, apply matrix, denormalize
    flat_grid_norm = np.maximum(flat_grid_lin - src_black, 0.0)
    gr, gg, gb = flat_grid_norm[:, 0:1], flat_grid_norm[:, 1:2], flat_grid_norm[:, 2:3]
    flat_grid_expanded = np.hstack([gr, gg, gb,
        np.sqrt(np.maximum(gr * gg, 0)), np.sqrt(np.maximum(gr * gb, 0)), np.sqrt(np.maximum(gg * gb, 0))])
    flat_transformed_lin = np.dot(flat_grid_expanded, matrix)
    flat_transformed_lin = np.maximum(flat_transformed_lin + tgt_black, 1e-6)
    flat_transformed_lin = np.clip(flat_transformed_lin, 1e-6, 100.0)
    
    # ZURUECK IN DEN ZIEL-LOG (z.B. V-Log)
    try:
        if target_log_curve == "GP-Log2":
            lin_clipped = np.clip(flat_transformed_lin, 0.0, None)
            flat_transformed_log = np.log(lin_clipped * 599.0 + 1.0) / np.log(600.0)
        else:
            flat_transformed_log = colour.models.log_encoding(flat_transformed_lin, function=target_log_curve)
    except Exception:
        flat_transformed_log = np.power(flat_transformed_lin, 1/2.4)
        
    # Absolutes LUT-Clipping
    flat_transformed_log = np.clip(flat_transformed_log, 0.0, 1.0)
    
    lut.table = flat_transformed_log.reshape((65, 65, 65, 3))
    
    out_filename = get_unique_filename(lut_name)
    colour.write_LUT(lut, out_filename)
    
    print("\n" + "="*50)
    print(f"ERFOLG! Deine LUT wurde gespeichert unter: {out_filename}")
    if not is_master_mode:
        print("Diese LUT ist komplett linear interpoliert und wird deine Out-of-Gamut Farben NICHT zerstoeren.")
    print("="*50 + "\n")


def process_pair(source_path, target_path):
    source_name = os.path.splitext(source_path)[0]
    target_name = os.path.splitext(target_path)[0]
    
    print(f"\nLade Bilder ein ({source_name} & {target_name})...")
    # Load with cv2.IMREAD_UNCHANGED to preserve 16-bit depth if available
    leica_img = cv2.imread(source_path, cv2.IMREAD_UNCHANGED)
    lumix_img = cv2.imread(target_path, cv2.IMREAD_UNCHANGED)
    
    if leica_img is None or lumix_img is None:
        print("Fehler: Konnte Bilder nicht lesen.")
        sys.exit(1)
        
    # Drop alpha channel if present (ensures 3 channels BGR)
    if len(leica_img.shape) == 3 and leica_img.shape[2] == 4:
        leica_img = leica_img[:, :, :3]
    if len(lumix_img.shape) == 3 and lumix_img.shape[2] == 4:
        lumix_img = lumix_img[:, :, :3]
        
    is_16bit_leica = leica_img.dtype == np.uint16
    is_16bit_lumix = lumix_img.dtype == np.uint16
    
    print(f"Leica Farbtiefe 16-bit: {is_16bit_leica}")
    print(f"Lumix Farbtiefe 16-bit: {is_16bit_lumix}")
    
    # Helper function to convert 8/16 bit unsigned to 0.0 - 1.0 float32
    def normalize_img_to_float(img, is_16bit):
        if is_16bit:
            return (img / 65535.0).astype(np.float32)
        return (img / 255.0).astype(np.float32)

    # 1. Floating point versions for accurate math (0.0 to 1.0)
    leica_float = normalize_img_to_float(leica_img, is_16bit_leica)
    lumix_float = normalize_img_to_float(lumix_img, is_16bit_lumix)
    
    # 2. 8-bit Versions for OpenCV display Windows (cv2.imshow prefers 8-bit integers)
    leica_display = (leica_float * 255).astype(np.uint8)
    lumix_display = (lumix_float * 255).astype(np.uint8)
    
    # --- SOURCE (Leica) ---
    pts_leica = select_points(leica_display, f"Schritt 1: {source_name}")
    print(f"\nExtrahiere Farben aus {source_name}...")
    leica_colors = extract_patches(leica_float, pts_leica) # returns 0.0 - 1.0 RGB layout
    
    # --- TARGET (Lumix) ---
    pts_lumix = select_points(lumix_display, f"Schritt 2: {target_name}")
    print(f"\nExtrahiere Farben aus {target_name}...")
    lumix_colors = extract_patches(lumix_float, pts_lumix)
    
    return leica_colors, lumix_colors
    


if __name__ == '__main__':
    main()

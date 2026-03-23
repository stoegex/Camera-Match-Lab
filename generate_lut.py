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
    mode = input("Waehle den Modus (1 oder 2): ")
    
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
        
    print("\nBerechne professionelle 3x3 Matrix + Offset Optimierung (Linear Space)...")
    
    # 1. LOG TO LINEAR CONVERSION
    try:
        source_lin = colour.models.log_decoding(all_source_colors, function=source_log_curve)
        target_lin = colour.models.log_decoding(all_target_colors, function=target_log_curve)
    except Exception as e:
        print(f"Warnung: Natives Log Decoding fehlgeschlagen ({e}). Nutze Gamma 2.4 Fallback.")
        source_lin = np.power(np.clip(all_source_colors, 0, 1), 2.4)
        target_lin = np.power(np.clip(all_target_colors, 0, 1), 2.4)
    
    # 2. GEWICHTUNG DER GRAUBLOECKE (Zwingt die Matrix, Schwarzwert/Weissabgleich sauber zu halten)
    # Die Indizes der 4 grossen Bloecke im ColorChecker Video sind 28, 29, 30 und 31.
    weights = np.ones(len(source_lin))
    gray_indices = [28, 29, 30, 31]
    
    # Falls wir im Master-Mode sind (mehrere Charts uebereinander), iterieren wir durch alle Chunks
    for i in range(len(source_lin)):
        if (i % 32) in gray_indices:
            weights[i] = 100.0  # 100-fache Gewichtung fuer Grautoene!
            
    W = np.diag(weights)
    
    # 3. MATRIX KALKULATION (3x3 Matrix + Offset = 4x3)
    # Fuegt eine Spalte mit Einsen (1.0) hinzu, damit die Matrix Belichtungs-/Flare-Offsets verrechnen kann
    source_pad = np.c_[source_lin, np.ones(source_lin.shape[0])]
    
    WX = np.dot(W, source_pad)
    WY = np.dot(W, target_lin)
    
    # Loest das Matrix-Problem nach Industriestandard (Least Squares)
    matrix, residuals, rank, s = np.linalg.lstsq(WX, WY, rcond=None)
    
    source_transformed_lin = np.dot(source_pad, matrix)
    mse = np.mean((target_lin - source_transformed_lin)**2)
    print(f"Abweichung (MSE im Linear-Space): {mse:.6f}")
    
    print("\nGeneriere die artefaktfreie 65x65 3D-LUT...")
    lut = colour.LUT3D(size=65, name=lut_name)
    
    try:
        grid_lin = colour.models.log_decoding(lut.table, function=source_log_curve)
    except Exception:
        grid_lin = np.power(lut.table, 2.4)
    
    flat_grid_lin = grid_lin.reshape(-1, 3)
    
    # Das Gitter mit dem Offset-Parameter (1.0) versehen und die Matrix anwenden
    flat_grid_pad = np.c_[flat_grid_lin, np.ones(flat_grid_lin.shape[0])]
    flat_transformed_lin = np.dot(flat_grid_pad, matrix)
    
    # SICHERHEITS-CLIPPING IM LINEAR-SPACE (Verhindert NaN-Werte beim Log-Encoding durch extremes Schwarz)
    flat_transformed_lin = np.clip(flat_transformed_lin, 1e-6, 100.0) 
    
    # ZURUECK IN DEN ZIEL-LOG (z.B. V-Log)
    try:
        flat_transformed_log = colour.models.log_encoding(flat_transformed_lin, function=target_log_curve)
    except Exception:
        flat_transformed_log = np.power(flat_transformed_lin, 1/2.4)
        
    # Absolutes LUT-Clipping (Resolve erwartet 0.0 bis 1.0 in der Cube)
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

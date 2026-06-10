// PHINGR Camera Frame — Minimal tripod, no screws, no drilling
// Triangle plate with 3 angled legs, rack-sleeve height adjustment
// RPi Zero 2W + IMX519 camera
//
// Print: top_plate() + 3x rack_sleeve()
// Hardware: 3x aluminum/carbon tubes (8mm OD, ~25cm) — off the shelf
//
// Rack sleeves slide over tubes, clamp tooth catches grooves.
// No screws, no drilling, fully 3D printable locking mechanism.

/* [Phone] */
phone_w = 67.3;      // iPhone SE3 width
phone_l = 138.4;     // iPhone SE3 length
phone_h = 7.3;       // iPhone SE3 thickness

/* [Tubes] */
tube_od = 8;         // tube outer diameter (mm)
tube_id_sleeve = 8.3;// sleeve inner diameter (slides over tube)
leg_spread = 25;     // how far legs are from phone edge
leg_angle = 10;      // outward angle of legs (degrees)

/* [Rack Sleeve] */
sleeve_od = 13;      // sleeve outer diameter
sleeve_wall = 2.35;  // (sleeve_od - tube_id_sleeve) / 2
sleeve_len = 200;    // sleeve length (adjust to tube length)
groove_w = 2.5;      // groove width
groove_d = 1.5;      // groove depth
groove_spacing = 5;  // distance between groove centers

/* [Clamp] */
clamp_hole = 13.4;   // clamp inner diameter (fits sleeve_od with clearance)
clamp_socket = 22;   // depth of tube socket in clamp
tooth_w = 2.2;       // spring tooth width (slightly less than groove)
tooth_d = 1.3;       // tooth depth (slightly less than groove depth)
tooth_flex = 0.8;    // slit width behind tooth for flex

/* [Plate] */
plate_thick = 4;
wall_thick = 5;
wall_height = 15;

/* [RPi Zero 2W] */
rpi_mount_w = 23;
rpi_mount_l = 58;
rpi_screw = 2.7;

/* [Camera] */
cam_hole = 12;

/* [Rendering] */
$fn = 50;

// ── Leg positions ───────────────────────────────────────────────────

leg_positions = [
    [-(phone_w/2 + leg_spread), -(phone_l/3)],
    [ (phone_w/2 + leg_spread), -(phone_l/3)],
    [ 0,                         (phone_l/2 + leg_spread)],
];

function leg_dir(pos) =
    let(len = sqrt(pos[0]*pos[0] + pos[1]*pos[1]))
    len > 0 ? [pos[0]/len, pos[1]/len] : [0, 0];

// ── Modules ─────────────────────────────────────────────────────────

module triangle_plate(positions, thick, inset=5) {
    hull() {
        for (pos = positions)
            translate([pos[0], pos[1], 0])
                cylinder(r=inset, h=thick);
    }
}

// ── Rack Sleeve (print 3x) ─────────────────────────────────────────
//
// Slides over the metal tube. Has vertical grooves on the outside
// that the clamp tooth catches.

module rack_sleeve() {
    num_grooves = floor((sleeve_len - 10) / groove_spacing);

    difference() {
        // Outer cylinder
        cylinder(d=sleeve_od, h=sleeve_len);

        // Inner hole (tube slides through)
        translate([0, 0, -0.5])
            cylinder(d=tube_id_sleeve, h=sleeve_len + 1);

        // Grooves along one side (flat face for tooth engagement)
        for (i = [0 : num_grooves - 1]) {
            z = 5 + i * groove_spacing;
            translate([sleeve_od/2 - groove_d, -groove_w/2, z])
                cube([groove_d + 1, groove_w, groove_w]);
        }

        // Second groove track (opposite side, for visual/optional dual tooth)
        for (i = [0 : num_grooves - 1]) {
            z = 5 + i * groove_spacing;
            translate([-(sleeve_od/2 + 1), -groove_w/2, z])
                cube([groove_d + 1, groove_w, groove_w]);
        }
    }

    // Flat faces for groove alignment (prevents sleeve from spinning)
    // Add two small flats
}

// Sleeve cross-section preview
module rack_sleeve_cross_section() {
    intersection() {
        rack_sleeve();
        translate([0, 0, sleeve_len/2])
            cube([sleeve_od + 2, sleeve_od + 2, 3], center=true);
    }
}

// ── Clamp with spring tooth ─────────────────────────────────────────

module tube_clamp(pos) {
    dir = leg_dir(pos);
    clamp_od = clamp_hole + 8;
    clamp_h = clamp_socket;

    translate([pos[0], pos[1], 0])
    rotate([dir[1] * leg_angle, -dir[0] * leg_angle, 0])
    translate([0, 0, -clamp_h + plate_thick])
    difference() {
        union() {
            // Clamp body
            cylinder(d=clamp_od, h=clamp_h);

            // Spring tooth bump (inside the clamp bore, on one side)
            // This catches the rack grooves
            translate([clamp_hole/2 - tooth_d, -tooth_w/2, clamp_h/2 - tooth_w/2])
                cube([tooth_d, tooth_w, tooth_w]);
        }

        // Sleeve bore (through)
        translate([0, 0, -0.5])
            cylinder(d=clamp_hole, h=clamp_h + 1);

        // Flex slit behind the tooth (allows it to deflect)
        // Arc-shaped slit on the tooth side
        translate([clamp_hole/2 + tooth_flex, -tooth_w, clamp_h/2 - tooth_w - 1])
            cube([tooth_flex, tooth_w * 2, tooth_w + 2]);

        // Release lever slot (can push tooth outward to disengage)
        translate([clamp_od/2 - 2, -1.5, clamp_h/2 - tooth_w/2 - 1])
            cube([3, 3, tooth_w + 2]);
    }
}

// ── Reinforcement wall ──────────────────────────────────────────────

module reinforcement_wall(pos_a, pos_b) {
    hull() {
        translate([pos_a[0], pos_a[1], -wall_height + plate_thick])
            cylinder(d=wall_thick, h=wall_height);
        translate([pos_b[0], pos_b[1], -wall_height + plate_thick])
            cylinder(d=wall_thick, h=wall_height);
    }
}

// ── Top Plate ───────────────────────────────────────────────────────

module top_plate() {
    union() {
        difference() {
            triangle_plate(leg_positions, plate_thick, inset=12);

            // Camera lens hole
            translate([0, 0, -0.5])
                cylinder(d=cam_hole, h=plate_thick + 2);

            // RPi mounting holes
            for (x = [-rpi_mount_w/2, rpi_mount_w/2])
                for (y = [-rpi_mount_l/2, rpi_mount_l/2])
                    translate([x, y, -0.5])
                        cylinder(d=rpi_screw, h=plate_thick + 2);

            // RPi standoff clearance
            for (x = [-rpi_mount_w/2, rpi_mount_w/2])
                for (y = [-rpi_mount_l/2, rpi_mount_l/2])
                    translate([x, y, -0.5])
                        cylinder(d=5.5, h=2);

            // CSI cable slot
            translate([0, -rpi_mount_l/2 - 5, -0.5])
                cube([18, 4, plate_thick + 2], center=true);

            // USB cable routing hole
            translate([0, -(phone_l/4), -0.5])
                cube([14, 6, plate_thick + 2], center=true);
        }

        // Tube clamps with spring tooth
        for (pos = leg_positions)
            tube_clamp(pos);

        // Reinforcement walls
        reinforcement_wall(leg_positions[0], leg_positions[1]);
        reinforcement_wall(leg_positions[1], leg_positions[2]);
        reinforcement_wall(leg_positions[2], leg_positions[0]);
    }
}

// ── Export ───────────────────────────────────────────────────────────

// Uncomment to render for printing:
// top_plate();
// rack_sleeve();   // print 3x

// ── Preview ─────────────────────────────────────────────────────────

module preview() {
    h = 200;

    // Top plate
    translate([0, 0, h])
        color("OrangeRed", 0.8) top_plate();

    // Tubes with sleeves
    for (pos = leg_positions) {
        dir = leg_dir(pos);
        translate([pos[0], pos[1], h])
            rotate([dir[1] * leg_angle, -dir[0] * leg_angle, 0])
                translate([0, 0, -h * 1.0]) {
                    // Metal tube inside
                    color("Silver", 0.3)
                        cylinder(d=tube_od, h=h * 1.1);
                    // Rack sleeve over tube
                    color("DodgerBlue", 0.5)
                        rack_sleeve();
                }
    }

    // Phone
    color("Black", 0.15)
        translate([0, 0, 0.5])
            cube([phone_w, phone_l, phone_h], center=true);

    // Screen
    color("White", 0.05)
        translate([0, 0, phone_h/2 + 0.5])
            cube([phone_w - 6, phone_l - 12, 0.5], center=true);

    // RPi
    color("Green", 0.2)
        translate([0, 0, h + plate_thick + 5])
            cube([30, 65, 1.5], center=true);

    // Ground
    color("DimGray", 0.1)
        translate([0, 0, -0.5])
            cube([300, 300, 1], center=true);

    // Show sleeve cross-section separately
    translate([130, 0, 0]) {
        color("DodgerBlue", 0.8)
            rack_sleeve_cross_section();
        translate([0, 0, -5])
            color("Silver", 0.5)
                cylinder(d=tube_od, h=3);
    }
}

preview();

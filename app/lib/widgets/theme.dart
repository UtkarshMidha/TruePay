import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';

// Design tokens: PreventNet design system (local/ui.css), light mode. Semantic colours keep one meaning each.
const cPage = Color(0xFFF2F2F6), cSurface = Color(0xFFFFFFFF), cRaised = Color(0xFFF7F7FB);
const cInk = Color(0xFF111118), cMuted = Color(0xFF45454F), cLine = Color(0xFFEBEBF1), cLine2 = Color(0xFFDFDFE8);
const cActive = Color(0xFF133D50), cActiveTint = Color(0xFFE3EEF2), cViolet = Color(0xFF2A6A85), cCyan = Color(0xFF3E8FAD);
const cNavy = Color(0xFF15151C), cConsole = Color(0xFF15151C);
const cPass = Color(0xFF178F60), cPassTint = Color(0xFFE4F5ED);
const cBlock = Color(0xFFD64541), cBlockTint = Color(0xFFFCEBEA);
const cHold = Color(0xFFB87404), cHoldTint = Color(0xFFFDF1DC);
const cIdle = Color(0xFF6E6E7C), cIdleTint = Color(0xFFF4F4F8);

/// PreventNet hero: deep violet (--hero-a -> --hero-b, 120deg).
const heroGradient = LinearGradient(
    colors: [Color(0xFF0B2633), Color(0xFF1A5068)], begin: Alignment.topLeft, end: Alignment.bottomRight);
/// PreventNet brand tile / accent buttons (--accent-2 -> --accent).
const accentGradient = LinearGradient(
    colors: [Color(0xFF2A6A85), Color(0xFF133D50)], begin: Alignment.topLeft, end: Alignment.bottomRight);

// Geist / Geist Mono (bundled, OFL). PreventNet uses weights 400-600 only: anything heavier is capped at 600.
FontWeight _cap(FontWeight w) => w.value > 600 ? FontWeight.w600 : w;
const typeScale = 1.15; // projector legibility: every size in the app x1.15
TextStyle _geist(String family, double size, FontWeight w, Color c, {double? spacing}) => TextStyle(
    fontFamily: family, fontSize: size * typeScale, fontWeight: _cap(w), color: c, height: 1.45, letterSpacing: spacing,
    fontVariations: [FontVariation('wght', _cap(w).value.toDouble())]);

/// Body 14, small 12.5; h1 22, h2 17, h3 14 (all 600, -0.01em).
TextStyle sans({double size = 14, FontWeight w = FontWeight.w400, Color c = cInk}) =>
    _geist('Geist', size, w, c, spacing: size >= 17 ? -0.01 * size : 0);
TextStyle mono({double size = 12.5, FontWeight w = FontWeight.w400, Color c = cInk}) => _geist('GeistMono', size, w, c);
TextStyle kpi(Color c) => _geist('Geist', 30, FontWeight.w600, c, spacing: -0.6)
    .copyWith(height: 1.15, fontFeatures: const [FontFeature.tabularFigures()]);

ThemeData appTheme() => ThemeData(
      scaffoldBackgroundColor: cPage,
      brightness: Brightness.light,
      fontFamily: 'Geist',
      colorScheme: ColorScheme.fromSeed(seedColor: cActive, primary: cActive, surface: cSurface),
      useMaterial3: true,
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.all(Colors.white),
        trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? null : cLine2),
        trackOutlineColor: WidgetStateProperty.all(Colors.transparent),
      ),
    );

/// .card: white, 1px --line, radius 16, soft shadow.
BoxDecoration card({Color color = cSurface, Color border = cLine, double r = 16}) => BoxDecoration(
    color: color,
    borderRadius: BorderRadius.circular(r),
    border: Border.all(color: border, width: 1),
    boxShadow: const [
      BoxShadow(color: Color(0x0A141428), blurRadius: 2, offset: Offset(0, 1)),
      BoxShadow(color: Color(0x0A141428), blurRadius: 16, offset: Offset(0, 4)),
    ]);

Color verdictColor(String? v) => switch (v) {
      'PASS' || 'ALLOW' => cPass,
      'BLOCK' || 'DENY' => cBlock,
      'INFO' => cActive,
      _ => cIdle,
    };
Color verdictTint(String? v) => switch (v) {
      'PASS' || 'ALLOW' => cPassTint,
      'BLOCK' || 'DENY' => cBlockTint,
      _ => cIdleTint,
    };

String euro(num? cents) {
  final c = (cents ?? 0).round();
  final s = (c ~/ 100).toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => ',');
  final rest = c % 100;
  return rest == 0 ? '€$s' : '€$s.${rest.toString().padLeft(2, '0')}';
}

String hms(dynamic ts) {
  if (ts is! Timestamp) return '--:--:--';
  final d = ts.toDate().toLocal();
  String p(int n) => n.toString().padLeft(2, '0');
  return '${p(d.hour)}:${p(d.minute)}:${p(d.second)}';
}

String maskIban(String? iban) {
  final s = (iban ?? '').replaceAll(' ', '');
  return s.length > 8 ? '${s.substring(0, 4)}…${s.substring(s.length - 4)}' : '…';
}

final db = FirebaseFirestore.instance;
Stream<Map<String, dynamic>> docStream(String path) => db.doc(path).snapshots().map((s) => s.data() ?? {});

Widget chip(String text, Color fg, Color bg) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Text(text, style: sans(size: 12, w: FontWeight.w500, c: fg)),
    );

class Stamp extends StatelessWidget {
  final String text;
  const Stamp(this.text, {super.key});
  @override
  Widget build(BuildContext context) => FittedBox(fit: BoxFit.scaleDown, child: Padding(padding: const EdgeInsets.all(18), child: Transform.rotate(
        angle: -8 * 3.14159 / 180,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 6),
          decoration: BoxDecoration(border: Border.all(color: cBlock, width: 4), borderRadius: BorderRadius.circular(8)),
          child: Text(text,
              style: sans(size: 44, w: FontWeight.w600, c: cBlock).copyWith(letterSpacing: 4, height: 1.1), softWrap: false, maxLines: 1),
        ),
      )));
}

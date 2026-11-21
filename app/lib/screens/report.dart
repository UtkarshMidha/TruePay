import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

import '../widgets/theme.dart';

// The report prints on white A4 paper, so it keeps its own light palette.
const rInk = Color(0xFF10213A), rMuted = Color(0xFF4E5D73), rLine = Color(0xFFD3DAE3);
TextStyle rs({double size = 14, FontWeight w = FontWeight.w400, Color c = rInk}) => sans(size: size, w: w, c: c);
TextStyle rm({double size = 13, FontWeight w = FontWeight.w400, Color c = rInk}) => mono(size: size, w: w, c: c);
BoxDecoration rCard({Color color = Colors.white}) =>
    BoxDecoration(color: color, borderRadius: BorderRadius.circular(12), border: Border.all(color: rLine));
Color rVerdict(String? v) => switch (v) {
      'PASS' || 'ALLOW' => const Color(0xFF0B7A55),
      'BLOCK' || 'DENY' => const Color(0xFFC21F3A),
      _ => rMuted,
    };

class ReportScreen extends StatelessWidget {
  const ReportScreen({super.key});

  Widget _kpi(String label, String v, Color c) => Expanded(
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: rCard(),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(v, style: kpi(c)),
            Text(label, style: rs(size: 12.5, c: rMuted)),
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Colors.white,
        body: Center(
          child: SizedBox(
            width: 794, // A4 at 96 dpi
            child: StreamBuilder<Map<String, dynamic>>(
              stream: docStream('config/runtime'),
              builder: (_, rt) => StreamBuilder<Map<String, dynamic>>(
                stream: docStream('stats/demo'),
                builder: (_, st) => StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
                  stream: db.collection('events').orderBy('ts').snapshots(),
                  builder: (_, ev) {
                    final r = rt.data ?? {}, s = st.data ?? {};
                    final rows = (ev.data?.docs ?? [])
                        .map((d) => d.data())
                        .where((e) => e['verdict'] == 'ALLOW' || e['verdict'] == 'DENY')
                        .toList();
                    final start = (r['session_started_at'] as Timestamp?)?.toDate().toLocal();
                    return ListView(padding: const EdgeInsets.all(32), children: [
                      Row(children: [
                        Text('Audit report', style: rs(size: 24, w: FontWeight.w600)),
                        const Spacer(),
                        OutlinedButton(onPressed: () => web.window.print(), child: const Text('Print or save as PDF')),
                      ]),
                      Text(
                          'Session ${start?.toString().substring(0, 16) ?? '—'} to ${DateTime.now().toString().substring(0, 16)} · '
                          'Operator ${FirebaseAuth.instance.currentUser?.email ?? ''}',
                          style: rs(c: rMuted)),
                      const SizedBox(height: 16),
                      Row(children: [
                        _kpi('Blocked', euro(s['blocked_cents']), cPass),
                        const SizedBox(width: 8),
                        _kpi('Paid', euro(s['paid_cents']), rInk),
                        const SizedBox(width: 8),
                        _kpi('Denied actions', '${s['denied_actions'] ?? 0}', rInk),
                        const SizedBox(width: 8),
                        _kpi('Runs', '${r['run_seq'] ?? 0}', rInk),
                      ]),
                      const SizedBox(height: 8),
                      Text('For comparison, the Act 0 baseline lost €18,950.', style: rs(c: const Color(0xFFC21F3A))),
                      const SizedBox(height: 16),
                      Table(
                        columnWidths: const {
                          0: FixedColumnWidth(72), 1: FixedColumnWidth(76), 2: FixedColumnWidth(96),
                          3: FixedColumnWidth(48), 4: FixedColumnWidth(64), 5: FlexColumnWidth(),
                        },
                        border: const TableBorder(horizontalInside: BorderSide(color: rLine)),
                        children: [
                          TableRow(children: [
                            for (final h in ['Time', 'Run', 'Actor', 'Layer', 'Verdict', 'Event'])
                              Padding(padding: const EdgeInsets.all(4), child: Text(h, style: rs(size: 12.5, w: FontWeight.w600, c: rMuted))),
                          ]),
                          for (final e in rows)
                            TableRow(children: [
                              _c(Text(hms(e['ts']), style: rm(size: 12))),
                              _c(Text('${e['run_id']}', style: rm(size: 12))),
                              _c(Text('${e['actor']}', style: rs(size: 12.5))),
                              _c(Text('${e['layer'] ?? ''}', style: rm(size: 12))),
                              _c(Text('${e['verdict']}', style: rm(size: 12, w: FontWeight.w600, c: rVerdict(e['verdict'])))),
                              _c(Text('${e['title']}  ${(e['codes'] as List?)?.join(' ') ?? ''}', style: rs(size: 12.5))),
                            ]),
                        ],
                      ),
                    ]);
                  },
                ),
              ),
            ),
          ),
        ),
      );

  Widget _c(Widget w) => Padding(padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 3), child: w);
}

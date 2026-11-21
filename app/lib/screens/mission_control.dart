import 'dart:async';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';

import '../scenarios.dart';
import '../widgets/theme.dart';
import 'approver.dart';

const masterIban = 'DE89370400440532013000';

String actOf(String? scenario, Map<String, dynamic> layers) => switch (scenario) {
      'baseline' => '0',
      'clean' => '1',
      'poisoned' => (layers['jailbreak_controller'] == true || layers['quarantine'] == false) ? '5' : '2',
      'swap' => '3',
      'insider' => '4',
      'judge' => 'judge',
      _ => 'idle',
    };

const banners = {
  'idle': ('Ready', 'Select a scenario to start a run.'),
  '0': ('Legacy AP automation', "Today's process: the IBAN printed on the invoice is paid after a TAN. No controls."),
  '1': ('INV-1001 · Standard invoice', 'Expected: every check passes, one approval, paid.'),
  '2': ('INV-1002 · Prompt injection', 'Hidden instructions for the AI, invisible to people.'),
  '3': ('INV-1003 · IBAN substitution', 'Same invoice as the legacy run, now through the agents and firewall.'),
  '4': ('Compromised service identity', 'The onboarding service calls the firewall directly with its own token.'),
  '5': ('Jailbroken controller', 'L1–L3 disabled and the controller follows the invoice. Only the firewall remains.'),
  'judge': ('Custom invoice', 'INV-1099'),
};

/// Rough number of events per act, for the progress bar while a run is in flight.
const expectedSteps = {'0': 6, '1': 16, '2': 10, '3': 18, '4': 9, '5': 10, 'judge': 12, 'idle': 1};

Stream<List<Map<String, dynamic>>> runEvents(String runId) => db
    .collection('events')
    .where('run_id', isEqualTo: runId)
    .orderBy('ts')
    .snapshots()
    .map((q) => q.docs.map((d) => d.data()).toList());

class MissionControl extends StatefulWidget {
  const MissionControl({super.key});
  @override
  State<MissionControl> createState() => _MissionControlState();
}

class _MissionControlState extends State<MissionControl> {
  StreamSubscription? _statsSub;
  Map<String, dynamic>? _prev;

  @override
  void initState() {
    super.initState();
    _statsSub = docStream('stats/demo').listen((s) async {
      final p = _prev;
      _prev = s;
      if (p == null || !mounted) return;
      final dBlocked = (s['blocked_cents'] ?? 0) - (p['blocked_cents'] ?? 0);
      final dLost = (s['lost_cents'] ?? 0) - (p['lost_cents'] ?? 0);
      if (dBlocked > 0) {
        final rt = (await db.doc('config/runtime').get()).data() ?? {};
        final inv = await db.collection('invoices').where('run_id', isEqualTo: rt['current_run_id']).limit(1).get();
        final reason = inv.docs.isEmpty ? 'policy' : (inv.docs.first.data()['hold_reason'] ?? 'policy');
        _toast(Icons.shield_rounded, 'Stopped ${euro(dBlocked)}', '$reason', cPass);
      }
      if (dLost > 0) _toast(Icons.warning_rounded, 'Lost ${euro(dLost)}', 'Transfer confirmed with a TAN', cBlock);
    });
  }

  void _toast(IconData icon, String title, String sub, Color c) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      behavior: SnackBarBehavior.floating,
      width: 420,
      backgroundColor: cNavy,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      duration: const Duration(milliseconds: 2500),
      content: Row(children: [
        Container(
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(8)),
          child: Icon(icon, color: Colors.white, size: 18),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: sans(c: Colors.white, w: FontWeight.w700)),
            Text(sub, style: sans(size: 12.5, c: Colors.white70), maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
      ]),
    ));
  }

  @override
  void dispose() {
    _statsSub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: StreamBuilder<Map<String, dynamic>>(
          stream: docStream('config/runtime'),
          builder: (context, rtSnap) => StreamBuilder<Map<String, dynamic>>(
            stream: docStream('config/layers'),
            builder: (context, lSnap) => StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
              stream: db.collection('commands').where('status', whereIn: ['NEW', 'RUNNING']).limit(1).snapshots(),
              builder: (context, cSnap) {
                final rt = rtSnap.data ?? {};
                final layers = {...defaultLayers, ...?lSnap.data};
                final runId = (rt['current_run_id'] ?? 'run-0000') as String;
                final scenario = rt['current_scenario'] as String?;
                final act = actOf(scenario, layers);
                final running = cSnap.data?.docs.isNotEmpty ?? false;
                return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Sidebar(busy: running, currentAct: act),
                  Expanded(
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.fromLTRB(28, 22, 28, 28),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        TopBar(act: act, running: running, runId: runId),
                        const SizedBox(height: 18),
                        const KpiRow(),
                        const SizedBox(height: 18),
                        Pipeline(runId: runId, act: act, running: running),
                        const SizedBox(height: 18),
                        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          SizedBox(width: 340, child: AgentProgress(runId: runId, act: act, running: running)),
                          const SizedBox(width: 18),
                          Expanded(child: Evidence(runId: runId, act: act)),
                        ]),
                        const SizedBox(height: 18),
                        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          SizedBox(width: 340, child: LayerRail(runId: runId, act: act, layers: layers)),
                          const SizedBox(width: 18),
                          Expanded(child: AgentLogs(runId: runId, running: running)),
                        ]),
                      ]),
                    ),
                  ),
                ]);
              },
            ),
          ),
        ),
      );
}

// ---------------------------------------------------------------- shared bits
Widget sectionTitle(String t, {Widget? trailing}) => Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(children: [
        Text(t, style: sans(size: 17, w: FontWeight.w600)),
        const Spacer(),
        if (trailing != null) trailing,
      ]),
    );

Widget overline(String t) => Padding(
      padding: const EdgeInsets.fromLTRB(4, 18, 4, 8),
      child: Text(t.toUpperCase(), style: sans(size: 11, w: FontWeight.w600, c: cIdle).copyWith(letterSpacing: 0.88)),
    );

Widget panel({required Widget child, EdgeInsets padding = const EdgeInsets.all(18)}) =>
    Container(padding: padding, decoration: card(), child: child);

Widget spinner({double size = 16, Color c = cActive}) =>
    SizedBox(width: size, height: size, child: CircularProgressIndicator(strokeWidth: 2.2, color: c));

// ---------------------------------------------------------------- sidebar
class Sidebar extends StatefulWidget {
  final bool busy;
  final String currentAct;
  const Sidebar({super.key, required this.busy, required this.currentAct});
  @override
  State<Sidebar> createState() => _SidebarState();
}

const scenarioIcons = {
  'legacy': Icons.history_rounded, 'clean': Icons.receipt_long_rounded, 'inject': Icons.visibility_off_rounded,
  'swap': Icons.swap_horiz_rounded, 'insider': Icons.vpn_key_off_rounded, 'jailbreak': Icons.psychology_alt_rounded,
  'custom': Icons.edit_note_rounded,
};

class _SidebarState extends State<Sidebar> {
  bool demo = true; // cached agent responses, ~10-15 s per run
  /// One click per act: set the layer switches the act needs, then queue the command (rules allow both).
  Future<void> run(Scenario s) async {
    await db.doc('config/layers').update(Map<String, Object>.from(s.act == '5' ? breachLayers : defaultLayers));
    await db.collection('commands').add({
      'scenario': s.key,
      'status': 'NEW',
      'created_at': FieldValue.serverTimestamp(),
      if (demo) 'note': 'demo',
    });
  }

  /// Clears runs, counters and switches (the runner performs it; the UI may only create commands).
  Future<void> _reset() => db.collection('commands').add({
        'scenario': 'judge', // any allowed key; the runner sees note == "reset" and never runs it
        'status': 'NEW',
        'note': 'reset',
        'created_at': FieldValue.serverTimestamp(),
      });

  Widget _scenario(Scenario s) {
    final dim = s.act == '0' || s.act == '5';
    final active = widget.busy && widget.currentAct == s.act;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: active ? cActiveTint : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: widget.busy ? null : () => run(s),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: active ? cActive.withValues(alpha: 0.35) : cLine),
            ),
            child: Row(children: [
              Container(
                width: 34,
                height: 34,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  gradient: dim ? null : accentGradient,
                  color: s.act == '0' ? cIdleTint : (s.act == '5' ? cBlockTint : null),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: active
                    ? spinner(size: 15, c: dim ? cActive : Colors.white)
                    : Icon(scenarioIcons[s.button], size: 18, color: s.act == '0' ? cMuted : (s.act == '5' ? cBlock : Colors.white)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(s.title, style: sans(size: 14, w: FontWeight.w600, c: widget.busy && !active ? cIdle : cInk), overflow: TextOverflow.ellipsis),
                  Text(s.subtitle, style: sans(size: 12.5, c: cMuted), overflow: TextOverflow.ellipsis),
                ]),
              ),
            ]),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Container(
        width: 290,
        decoration: const BoxDecoration(color: cSurface, border: Border(right: BorderSide(color: cLine))),
        child: ListView(padding: const EdgeInsets.fromLTRB(18, 22, 18, 22), children: [
          Row(children: [
            Container(
              decoration: BoxDecoration(borderRadius: BorderRadius.circular(14),
                  boxShadow: const [BoxShadow(color: Color(0x59133D50), blurRadius: 16, offset: Offset(0, 6))]),
              child: Image.asset('assets/brand/logo.png', width: 48, height: 48),
            ),
            const SizedBox(width: 12),
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('TruePay', style: sans(size: 19, w: FontWeight.w600)),
              Text('No fake IBAN gets paid', style: sans(size: 12.5, c: cMuted)),
            ]),
          ]),
          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.fromLTRB(12, 8, 6, 8),
            decoration: BoxDecoration(color: demo ? cActiveTint : cIdleTint, borderRadius: BorderRadius.circular(12)),
            child: Row(children: [
              Icon(demo ? Icons.bolt_rounded : Icons.cloud_rounded, size: 18, color: demo ? cActive : cMuted),
              const SizedBox(width: 8),
              Expanded(child: Text(demo ? 'Demo mode' : 'Live agents', style: sans(size: 13.5, w: FontWeight.w600))),
              Transform.scale(scale: 0.85, child: Switch(value: demo, onChanged: widget.busy ? null : (v) => setState(() => demo = v))),
            ]),
          ),
          overline('Scenarios'),
          for (final s in scenarioButtons) _scenario(s),
          const SizedBox(height: 14),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                    shape: const StadiumBorder(), foregroundColor: cInk, side: const BorderSide(color: cLine2), padding: const EdgeInsets.symmetric(vertical: 14)),
                onPressed: widget.busy ? null : _reset,
                icon: const Icon(Icons.restart_alt_rounded, size: 18),
                label: Text('Reset', style: sans(w: FontWeight.w500)),
              ),
            ),
          ]),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
                shape: const StadiumBorder(), foregroundColor: cInk, side: const BorderSide(color: cLine2), padding: const EdgeInsets.symmetric(vertical: 14)),
            onPressed: () => Navigator.pushNamed(context, '/report'),
            icon: const Icon(Icons.receipt_long_rounded, size: 18),
            label: Text('Audit report', style: sans(w: FontWeight.w500)),
          ),
        ]),
      );
}

// ---------------------------------------------------------------- top bar + KPIs
const presenterName = 'Utkarsh';

class TopBar extends StatelessWidget {
  final String act, runId;
  final bool running;
  const TopBar({super.key, required this.act, required this.running, required this.runId});
  @override
  Widget build(BuildContext context) => Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Hi, $presenterName', style: sans(size: 24, w: FontWeight.w600)),
            const SizedBox(height: 2),
            Text("Review today's invoices. Agents decide, code enforces, you approve.", style: sans(size: 14.5, c: cMuted)),
          ]),
        ),
        AnimatedContainer(
          duration: const Duration(milliseconds: 250),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: BoxDecoration(color: running ? cNavy : cSurface, borderRadius: BorderRadius.circular(999), border: Border.all(color: running ? cNavy : cLine2)),
          child: Row(children: [
            if (running) spinner(size: 15, c: Colors.white) else const Icon(Icons.verified_user_rounded, size: 17, color: cPass),
            const SizedBox(width: 8),
            Text(running ? 'Agents working…' : 'Firewall on · all clear', style: sans(size: 13.5, w: FontWeight.w600, c: running ? Colors.white : cInk)),
          ]),
        ),
      ]);
}

class KpiRow extends StatelessWidget {
  const KpiRow({super.key});

  Widget _counter(num? v, TextStyle style, {bool money = true}) => TweenAnimationBuilder<double>(
        tween: Tween(end: (v ?? 0).toDouble()),
        duration: const Duration(milliseconds: 800),
        curve: Curves.easeOutCubic,
        builder: (_, x, __) => Text(money ? euro(x) : x.round().toString(), style: style),
      );

  Widget _tile(IconData icon, String label, num? v, Color c, Color tint, {bool money = true}) => Expanded(
        flex: 6,
        child: Container(
          height: 112,
          padding: const EdgeInsets.all(16),
          decoration: card(),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Row(children: [
              Container(
                  padding: const EdgeInsets.all(7),
                  decoration: BoxDecoration(color: tint, borderRadius: BorderRadius.circular(10)),
                  child: Icon(icon, size: 18, color: c)),
              const SizedBox(width: 10),
              Expanded(child: Text(label, style: sans(size: 13, c: cMuted, w: FontWeight.w500))),
            ]),
            _counter(v, kpi(c), money: money),
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) => StreamBuilder<Map<String, dynamic>>(
        stream: docStream('stats/demo'),
        builder: (_, s) {
          final d = s.data ?? {};
          return Row(children: [
            Expanded(
              flex: 9,
              child: Container(
                height: 112,
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(gradient: heroGradient, borderRadius: BorderRadius.circular(20),
                    boxShadow: const [BoxShadow(color: Color(0x33133D50), blurRadius: 24, offset: Offset(0, 10))]),
                child: Row(children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                      Text('Blocked by TruePay', style: sans(size: 13, c: Colors.white70, w: FontWeight.w500)),
                      _counter(d['blocked_cents'], kpi(Colors.white).copyWith(fontSize: 32)),
                    ]),
                  ),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(14)),
                    child: const Icon(Icons.verified_user_rounded, color: Colors.white, size: 30),
                  ),
                ]),
              ),
            ),
            const SizedBox(width: 14),
            _tile(Icons.trending_down_rounded, 'Lost without TruePay', d['lost_cents'], cBlock, cBlockTint),
            const SizedBox(width: 14),
            _tile(Icons.payments_rounded, 'Paid', d['paid_cents'], cInk, cPassTint),
            const SizedBox(width: 14),
            _tile(Icons.gpp_bad_rounded, 'Denied actions', d['denied_actions'], cInk, cActiveTint, money: false),
          ]);
        },
      );
}

// ---------------------------------------------------------------- pipeline with a moving agent token
const nodeOf = {
  'intake': 'intake', 'sentinel': 'intake', 'model_armor': 'intake', 'baseline': 'intake',
  'controller': 'controller', 'onboarding': 'controller', 'investigator': 'investigator',
  'vendor_agent': 'vendor', 'firewall': 'firewall', 'human': 'human', 'bank': 'bank',
};
const nodes = ['intake', 'controller', 'investigator', 'vendor', 'firewall', 'human', 'bank'];
const nodeIcons = {
  'intake': Icons.document_scanner_rounded, 'controller': Icons.psychology_rounded, 'investigator': Icons.travel_explore_rounded,
  'vendor': Icons.storefront_rounded, 'firewall': Icons.security_rounded, 'human': Icons.phone_iphone_rounded,
  'bank': Icons.account_balance_rounded,
};

class Pipeline extends StatelessWidget {
  final String runId, act;
  final bool running;
  const Pipeline({super.key, required this.runId, required this.act, required this.running});

  String label(String n) => switch (n) {
        'intake' => act == '0' ? 'Legacy automation' : 'Intake',
        'controller' => act == '4' ? 'Onboarding svc' : 'Controller',
        'investigator' => 'Investigator',
        'vendor' => 'Vendor agent',
        'firewall' => 'Firewall',
        'human' => 'Approver',
        _ => 'Bank',
      };

  @override
  Widget build(BuildContext context) => panel(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
        child: StreamBuilder<List<Map<String, dynamic>>>(
          stream: runEvents(runId),
          builder: (_, s) {
            final evs = s.data ?? const <Map<String, dynamic>>[];
            final latest = <String, Map<String, dynamic>>{};
            String? current;
            for (final e in evs) {
              final n = nodeOf[e['actor']];
              if (n != null) {
                latest[n] = e;
                current = n;
              }
            }
            final idx = current == null ? (running ? 0 : -1) : nodes.indexOf(current);
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(banners[act]!.$1, style: sans(size: 12.5, w: FontWeight.w600, c: cActive)),
              const SizedBox(height: 2),
              sectionTitle(banners[act]!.$2,
                  trailing: chip(running ? 'LIVE' : (evs.isEmpty ? 'STANDBY' : 'COMPLETE'),
                      running ? cActive : (evs.isEmpty ? cIdle : cPass), running ? cActiveTint : (evs.isEmpty ? cIdleTint : cPassTint))),
              LayoutBuilder(builder: (context, box) {
                final step = box.maxWidth / nodes.length;
                return SizedBox(
                  height: 132,
                  child: Stack(clipBehavior: Clip.none, children: [
                    // rail
                    Positioned(left: step / 2, right: step / 2, top: 58, child: Container(height: 2, color: cLine)),
                    if (idx >= 0)
                      AnimatedPositioned(
                        duration: const Duration(milliseconds: 700),
                        curve: Curves.easeInOutCubic,
                        left: step / 2,
                        top: 58,
                        width: step * idx,
                        child: Container(height: 2, decoration: const BoxDecoration(gradient: accentGradient)),
                      ),
                    for (var i = 0; i < nodes.length; i++)
                      Positioned(
                        left: step * i,
                        width: step,
                        top: 28,
                        child: _Node(
                          label: label(nodes[i]),
                          icon: nodeIcons[nodes[i]]!,
                          ev: act == '0' && !['intake', 'human', 'bank'].contains(nodes[i]) ? null : latest[nodes[i]],
                          notInstalled: act == '0' && !['intake', 'human', 'bank'].contains(nodes[i]),
                          active: running && i == idx,
                          dashed: nodes[i] == 'vendor',
                        ),
                      ),
                    // the moving agent token
                    if (idx >= 0)
                      AnimatedPositioned(
                        duration: const Duration(milliseconds: 700),
                        curve: Curves.easeInOutCubic,
                        left: step * idx + step / 2 - 15,
                        top: 0,
                        child: _AgentToken(running: running, label: current == null ? 'start' : label(current)),
                      ),
                  ]),
                );
              }),
            ]);
          },
        ),
      );
}

class _AgentToken extends StatefulWidget {
  final bool running;
  final String label;
  const _AgentToken({required this.running, required this.label});
  @override
  State<_AgentToken> createState() => _AgentTokenState();
}

class _AgentTokenState extends State<_AgentToken> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse = AnimationController(vsync: this, duration: const Duration(milliseconds: 900))..repeat(reverse: true);
  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _pulse,
        builder: (_, child) => Transform.translate(offset: Offset(0, widget.running ? -3 * _pulse.value : 0), child: child),
        child: Tooltip(
          message: 'Work is at: ${widget.label}',
          child: Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              gradient: accentGradient,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white, width: 2),
              boxShadow: const [BoxShadow(color: Color(0x55133D50), blurRadius: 12, offset: Offset(0, 4))],
            ),
            child: const Icon(Icons.smart_toy_rounded, size: 16, color: Colors.white),
          ),
        ),
      );
}

class _Node extends StatelessWidget {
  final String label;
  final IconData icon;
  final Map<String, dynamic>? ev;
  final bool notInstalled, active, dashed;
  const _Node({required this.label, required this.icon, this.ev, this.notInstalled = false, this.active = false, this.dashed = false});

  @override
  Widget build(BuildContext context) {
    final v = ev?['verdict'] as String?;
    final c = notInstalled ? cIdle : (active ? cActive : verdictColor(v));
    final bg = notInstalled || v == null ? cIdleTint : (v == 'INFO' ? cActiveTint : verdictTint(v));
    final badge = switch (v) {
      'PASS' || 'ALLOW' => Icons.check_rounded,
      'BLOCK' || 'DENY' => Icons.close_rounded,
      _ => null,
    };
    return Column(children: [
      SizedBox(
        width: 60,
        height: 60,
        child: Stack(alignment: Alignment.center, children: [
          if (active) const SizedBox(width: 60, height: 60, child: CircularProgressIndicator(strokeWidth: 3, color: cActive)),
          AnimatedContainer(
            duration: const Duration(milliseconds: 250),
            width: 50,
            height: 50,
            decoration: BoxDecoration(
              color: bg,
              shape: BoxShape.circle,
              border: Border.all(color: v == null && !active ? cLine : c, width: dashed ? 1.2 : 2),
            ),
            child: Icon(icon, size: 22, color: notInstalled ? cIdle : (v == null && !active ? cIdle : c)),
          ),
          if (badge != null && !active)
            Positioned(
              right: 2,
              bottom: 2,
              child: Container(
                padding: const EdgeInsets.all(2),
                decoration: BoxDecoration(color: c, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)),
                child: Icon(badge, size: 11, color: Colors.white),
              ),
            ),
        ]),
      ),
      const SizedBox(height: 6),
      Text(label, style: sans(size: 12.5, w: FontWeight.w700), maxLines: 1, overflow: TextOverflow.ellipsis),
      Text(notInstalled ? '—' : (dashed && ev == null ? 'A2A' : (ev?['title'] ?? '—')),
          maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.center, style: sans(size: 11, c: cMuted)),
    ]);
  }
}

// ---------------------------------------------------------------- agent progress (step list)
const actorNames = {
  'baseline': 'Legacy automation', 'intake': 'Intake', 'sentinel': 'Gemma Sentinel', 'model_armor': 'Model Armor',
  'controller': 'Controller', 'investigator': 'Investigator', 'onboarding': 'Onboarding service',
  'vendor_agent': 'Vendor agent (A2A)', 'firewall': 'Policy firewall', 'human': 'Approver', 'bank': 'Bank',
};

class AgentProgress extends StatelessWidget {
  final String runId, act;
  final bool running;
  const AgentProgress({super.key, required this.runId, required this.act, required this.running});

  @override
  Widget build(BuildContext context) => panel(
        child: StreamBuilder<List<Map<String, dynamic>>>(
          stream: runEvents(runId),
          builder: (_, s) {
            final evs = (s.data ?? const <Map<String, dynamic>>[]).where((e) => e['type'] != 'TOOL_CALL' || e['actor'] != 'firewall').toList();
            final total = expectedSteps[act] ?? 10;
            final progress = running ? (evs.length / total).clamp(0.05, 0.92) : (evs.isEmpty ? 0.0 : 1.0);
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              sectionTitle('Agent progress',
                  trailing: running
                      ? Row(children: [spinner(size: 13), const SizedBox(width: 6), Text('Running', style: sans(size: 12.5, w: FontWeight.w600, c: cActive))])
                      : (evs.isEmpty ? chip('IDLE', cIdle, cIdleTint) : chip('DONE', cPass, cPassTint))),
              Text(runId, style: mono(size: 12, c: cMuted)),
              const SizedBox(height: 10),
              ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: TweenAnimationBuilder<double>(
                  tween: Tween(end: progress),
                  duration: const Duration(milliseconds: 500),
                  builder: (_, v, __) => LinearProgressIndicator(value: v, minHeight: 6, backgroundColor: const Color(0xFFEFEFF4), color: cActive),
                ),
              ),
              const SizedBox(height: 12),
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 470),
                child: evs.isEmpty && !running
                    ? Padding(
                        padding: const EdgeInsets.symmetric(vertical: 28),
                        child: Column(children: [
                          const Icon(Icons.play_circle_outline_rounded, size: 34, color: cIdle),
                          const SizedBox(height: 6),
                          Text('Start a scenario to see each agent step.', style: sans(size: 13, c: cMuted)),
                        ]),
                      )
                    // reverse: pinned to the newest step, older steps scroll up (like a live checklist)
                    : ListView(shrinkWrap: true, reverse: true, children: [
                        if (running) _pendingStep(),
                        for (var i = evs.length - 1; i >= 0; i--) _step(evs[i], isLast: i == evs.length - 1),
                      ]),
              ),
            ]);
          },
        ),
      );

  Widget _box(Widget child, Color bg) => Container(
        width: 30,
        height: 30,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(9)),
        child: child,
      );

  Widget _step(Map<String, dynamic> e, {required bool isLast}) {
    final v = e['verdict'] as String?;
    final icon = switch (v) {
      'PASS' || 'ALLOW' => _box(const Icon(Icons.check_rounded, size: 17, color: cPass), cPassTint),
      'BLOCK' || 'DENY' => _box(const Icon(Icons.close_rounded, size: 17, color: cBlock), cBlockTint),
      _ => _box(const Icon(Icons.circle, size: 7, color: cActive), cActiveTint),
    };
    final codes = (e['codes'] as List?)?.join(' ') ?? '';
    return TweenAnimationBuilder<double>(
      key: ValueKey('${e['ts']}${e['title']}'),
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 300),
      builder: (_, x, child) => Opacity(opacity: x, child: Transform.translate(offset: Offset(0, 8 * (1 - x)), child: child)),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 8),
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: cLine))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          icon,
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${e['title']}', style: sans(size: 13, w: FontWeight.w600, c: v == 'BLOCK' || v == 'DENY' ? cBlock : cInk)),
              Text('${actorNames[e['actor']] ?? e['actor']}${e['layer'] != null ? ' · ${e['layer']}' : ''}${codes.isNotEmpty ? ' · $codes' : ''}',
                  style: sans(size: 11.5, c: cMuted), maxLines: 1, overflow: TextOverflow.ellipsis),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _pendingStep() => Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(children: [
          _box(spinner(size: 15), cActiveTint),
          const SizedBox(width: 10),
          Text('Working on the next step…', style: sans(size: 13, w: FontWeight.w600, c: cActive)),
        ]),
      );
}

// ---------------------------------------------------------------- agent logs console
class AgentLogs extends StatelessWidget {
  final String runId;
  final bool running;
  const AgentLogs({super.key, required this.runId, required this.running});

  static const _actorColors = {
    'controller': Color(0xFF7DD3FC), 'investigator': Color(0xFF5EEAD4), 'vendor_agent': Color(0xFF38BDF8),
    'firewall': Color(0xFF34D399), 'human': Color(0xFFFBBF24), 'bank': Color(0xFFFBBF24), 'onboarding': Color(0xFFFB7185),
  };

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(color: cConsole, borderRadius: BorderRadius.circular(16), boxShadow: const [BoxShadow(color: Color(0x14141428), blurRadius: 16, offset: Offset(0, 4))]),
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            for (final c in const [Color(0xFFFB7185), Color(0xFFFBBF24), Color(0xFF34D399)])
              Container(margin: const EdgeInsets.only(right: 6), width: 10, height: 10, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
            const SizedBox(width: 8),
            Text('Agent logs', style: sans(size: 13.5, w: FontWeight.w700, c: Colors.white)),
            const SizedBox(width: 8),
            Text(runId, style: mono(size: 12, c: Colors.white54)),
            const Spacer(),
            if (running) spinner(size: 12, c: const Color(0xFF7DD3FC)),
            const SizedBox(width: 6),
            Text(running ? 'streaming' : 'live', style: mono(size: 11.5, c: Colors.white54)),
          ]),
          const SizedBox(height: 10),
          SizedBox(
            height: 300,
            child: StreamBuilder<List<Map<String, dynamic>>>(
              stream: runEvents(runId),
              builder: (_, s) {
                final evs = (s.data ?? const <Map<String, dynamic>>[]).reversed.toList(); // newest first
                if (evs.isEmpty) {
                  return Center(child: Text('\$ waiting for the first agent step…', style: mono(size: 12.5, c: Colors.white38)));
                }
                return ListView.builder(
                  itemCount: evs.length,
                  itemBuilder: (_, i) {
                    final e = evs[i];
                    final v = e['verdict'] as String? ?? 'INFO';
                    final vc = switch (v) {
                      'PASS' || 'ALLOW' => const Color(0xFF34D399),
                      'BLOCK' || 'DENY' => const Color(0xFFFB7185),
                      _ => const Color(0xFF7DD3FC),
                    };
                    final codes = (e['codes'] as List?)?.join(' ') ?? '';
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: SelectableText.rich(TextSpan(style: mono(size: 12.5, c: Colors.white70), children: [
                        TextSpan(text: '${hms(e['ts'])}  ', style: mono(size: 12.5, c: Colors.white38)),
                        TextSpan(text: '${(e['actor'] ?? '').toString().padRight(13)}', style: mono(size: 12.5, c: _actorColors[e['actor']] ?? Colors.white70, w: FontWeight.w600)),
                        TextSpan(text: '${v.padRight(6)}', style: mono(size: 12.5, c: vc, w: FontWeight.w700)),
                        TextSpan(text: '${e['title']}', style: mono(size: 12.5, c: Colors.white)),
                        if (codes.isNotEmpty) TextSpan(text: '  [$codes]', style: mono(size: 12.5, c: const Color(0xFFFB7185))),
                        if ((e['detail'] ?? '').toString().isNotEmpty) TextSpan(text: '\n${' ' * 10}↳ ${e['detail']}', style: mono(size: 11.5, c: Colors.white38)),
                      ])),
                    );
                  },
                );
              },
            ),
          ),
        ]),
      );
}

// ---------------------------------------------------------------- evidence: invoice + what the agents see / phone mirror
class Evidence extends StatelessWidget {
  final String runId, act;
  const Evidence({super.key, required this.runId, required this.act});

  @override
  Widget build(BuildContext context) => StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
        stream: db.collection('invoices').where('run_id', isEqualTo: runId).limit(1).snapshots(),
        builder: (_, s) {
          final inv = (s.data?.docs.isNotEmpty ?? false) ? s.data!.docs.first.data() : <String, dynamic>{};
          final fixture = (inv['fixture'] as String?) ?? (act == '0' ? 'INV-1003' : null);
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _Paper(fixture: fixture, inv: inv, act: act),
            const SizedBox(width: 18),
            Expanded(child: _RightCard(inv: inv, act: act)),
          ]);
        },
      );
}

class _Paper extends StatelessWidget {
  final String? fixture;
  final Map<String, dynamic> inv;
  final String act;
  const _Paper({required this.fixture, required this.inv, required this.act});
  @override
  Widget build(BuildContext context) {
    final spans = (inv['hidden_spans'] as List?) ?? const [];
    return SizedBox(
      width: 330,
      child: panel(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          sectionTitle('Invoice', trailing: fixture == null ? null : Text(fixture!, style: mono(size: 12, c: cMuted))),
          if (fixture == null)
            SizedBox(
              height: 220,
              child: Center(
                child: Text(act == '4' ? 'No invoice: an insider component acts directly' : 'No invoice yet',
                    textAlign: TextAlign.center, style: sans(c: cMuted)),
              ),
            )
          else
            StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
              stream: db.collection('baseline_transfers').limit(1).snapshots(),
              builder: (_, bt) {
                final lost = act == '0' && (bt.data?.docs.isNotEmpty ?? false);
                final blocked = inv['status'] == 'HOLD';
                return Stack(alignment: Alignment.center, children: [
                  Container(
                    alignment: Alignment.center,
                    decoration: BoxDecoration(color: cIdleTint, borderRadius: BorderRadius.circular(10), border: Border.all(color: cLine)),
                    padding: const EdgeInsets.all(6),
                    child: _InvoiceImage(fixture!, spans, inv['page_size'] as Map?),
                  ),
                  if (blocked || lost) Stamp(lost ? 'LOST' : 'BLOCKED'),
                ]);
              },
            ),
          if (spans.isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: card(color: cBlockTint, border: cBlock.withValues(alpha: 0.4), r: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  const Icon(Icons.visibility_rounded, size: 16, color: cBlock),
                  const SizedBox(width: 6),
                  Text('Hidden text revealed', style: sans(size: 13, w: FontWeight.w700, c: cBlock)),
                ]),
                const SizedBox(height: 6),
                for (final sp in spans) Text('${sp['text']}', style: mono(size: 11.5, c: cBlock)),
              ]),
            ),
          ],
        ]),
      ),
    );
  }
}

/// Invoice PNG with a red box over every hidden span (coordinates in PDF points).
class _InvoiceImage extends StatelessWidget {
  final String fixture;
  final List spans;
  final Map? page;
  const _InvoiceImage(this.fixture, this.spans, this.page);
  @override
  Widget build(BuildContext context) {
    const h = 400.0;
    final pw = (page?['w'] as num?)?.toDouble() ?? 595.0, ph = (page?['h'] as num?)?.toDouble() ?? 842.0;
    final w = h * pw / ph, sx = w / pw, sy = h / ph;
    return SizedBox(
      width: w,
      height: h,
      child: Stack(children: [
        Container(
          decoration: BoxDecoration(boxShadow: const [BoxShadow(color: Color(0x140F172A), blurRadius: 10, offset: Offset(0, 3))], borderRadius: BorderRadius.circular(4)),
          child: ClipRRect(borderRadius: BorderRadius.circular(4), child: Image.asset('assets/invoices/$fixture.png', width: w, height: h, fit: BoxFit.fill)),
        ),
        for (final sp in spans)
          Positioned(
            left: (sp['x0'] as num) * sx - 3,
            top: (sp['top'] as num) * sy - 3,
            width: ((sp['x1'] as num) - (sp['x0'] as num)) * sx + 6,
            height: (((sp['bottom'] as num) - (sp['top'] as num)) * sy).clamp(2.0, h) + 6,
            child: Container(decoration: BoxDecoration(color: cBlock.withValues(alpha: 0.15), border: Border.all(color: cBlock, width: 2))),
          ),
      ]),
    );
  }
}

class _RightCard extends StatelessWidget {
  final Map<String, dynamic> inv;
  final String act;
  const _RightCard({required this.inv, required this.act});

  Widget row(String k, Widget v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 9),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 120, child: Text(k, style: sans(size: 13, c: cMuted))),
          Expanded(child: v),
        ]),
      );

  Widget mirror(Widget phoneCard) => panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          sectionTitle('Approver device', trailing: chip('MIRRORED', cActive, cActiveTint)),
          phoneCard,
        ]),
      );

  @override
  Widget build(BuildContext context) => LiveDoc(
        'approvals',
        (d) => mirror(ApprovalCard(doc: d, readOnly: true)),
        fallback: LiveDoc(
          'baseline_confirmations',
          (d) => mirror(BankCard(doc: d, readOnly: true)),
          fallback: Builder(builder: (context) {
            if (act == '0') {
              return panel(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  sectionTitle('What the automation saw', trailing: chip('NO CHECKS', cBlock, cBlockTint)),
                  row('IBAN', Text('DE39 9999 9999 0012 3456 78', style: mono())),
                  row('Amount', Text('€18,950.00', style: sans(w: FontWeight.w700))),
                  const SizedBox(height: 6),
                  Text('Pays the IBAN printed on the invoice. No vendor check.', style: sans(size: 13, c: cMuted)),
                ]),
              );
            }
            if (inv.isEmpty) {
              return panel(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  sectionTitle('What the agents see'),
                  Text('Nothing yet. Agents only ever get extracted fields, never the raw document.', style: sans(size: 13, c: cMuted)),
                ]),
              );
            }
            final iban = (inv['iban'] ?? '') as String;
            final isMaster = iban == masterIban;
            final status = (inv['status'] ?? '') as String;
            final withheld = ((inv['suspicious_instructions'] as List?)?.length ?? 0);
            final hidden = ((inv['hidden_spans'] as List?)?.length ?? 0);
            final n = withheld > 0 ? withheld : hidden;
            final (fg, bg) = switch (status) {
              'HOLD' || 'QUARANTINED' || 'FLAGGED' || 'REJECTED' => (cBlock, cBlockTint),
              'PAID' || 'VERIFIED' || 'SCREENED' => (cPass, cPassTint),
              'PENDING_APPROVAL' => (cHold, cHoldTint),
              _ => (cIdle, cIdleTint),
            };
            return panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                sectionTitle('What the agents see', trailing: chip(status, fg, bg)),
                Text(euro(inv['amount_cents']), style: sans(size: 30, w: FontWeight.w800)),
                Text('${inv['vendor_name'] ?? '—'}', style: sans(size: 13.5, c: cMuted)),
                const SizedBox(height: 8),
                const Divider(color: cLine, height: 1),
                row('Invoice / order', Text('${inv['invoice_no'] ?? '—'} · ${inv['po_number'] ?? '—'}', style: mono(size: 13))),
                row(
                    'IBAN',
                    Wrap(spacing: 8, runSpacing: 4, children: [
                      Text(maskIban(iban), style: mono(size: 13)),
                      chip(isMaster ? '= master' : '≠ master …3000', isMaster ? cPass : cBlock, isMaster ? cPassTint : cBlockTint),
                    ])),
                if ((inv['hold_reason'] ?? '').toString().isNotEmpty)
                  row('Hold reason', Text('${inv['hold_reason']}', style: sans(size: 13, w: FontWeight.w600, c: cBlock))),
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(color: cIdleTint, borderRadius: BorderRadius.circular(10)),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Icon(Icons.info_outline_rounded, size: 16, color: cMuted),
                    const SizedBox(width: 8),
                    Expanded(child: Text('${inv['notice'] ?? ''}', style: sans(size: 12.5, c: cMuted))),
                  ]),
                ),
                if (n > 0) ...[
                  const SizedBox(height: 10),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(color: cBlockTint, borderRadius: BorderRadius.circular(10)),
                    child: Row(children: [
                      const Icon(Icons.block_rounded, size: 16, color: cBlock),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text('Withheld from agents: $n hidden instruction${n > 1 ? 's' : ''} (operator only)',
                            style: sans(size: 12.5, c: cBlock, w: FontWeight.w600)),
                      ),
                    ]),
                  ),
                ],
              ]),
            );
          }),
        ),
      );
}

// ---------------------------------------------------------------- defense layers
const layerNames = {
  'L1': 'Hidden-text scan', 'L2': 'Model Armor', 'L3': 'Sentinel (Gemma)',
  'L4': 'Vendor verification', 'L5': 'Policy firewall', 'L6': 'Human approval',
};
const layerSwitch = {'L1': 'hidden_text', 'L2': 'model_armor', 'L3': 'quarantine'};

class LayerRail extends StatelessWidget {
  final String runId, act;
  final Map<String, dynamic> layers;
  const LayerRail({super.key, required this.runId, required this.act, required this.layers});

  @override
  Widget build(BuildContext context) => panel(
        child: StreamBuilder<List<Map<String, dynamic>>>(
          stream: runEvents(runId),
          builder: (_, s) {
            final latest = <String, Map<String, dynamic>>{};
            for (final e in s.data ?? const []) {
              if (e['layer'] != null) latest[e['layer'] as String] = e;
            }
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              sectionTitle('Defense layers'),
              if (act == '0')
                Text('No controls in legacy automation.', style: sans(size: 13.5, c: cMuted))
              else
                for (final l in layerNames.keys) _layerRow(l, latest[l]),
            ]);
          },
        ),
      );

  Widget _layerRow(String l, Map<String, dynamic>? ev) {
    final v = ev?['verdict'] as String?;
    final disabled = layerSwitch.containsKey(l) && layers[layerSwitch[l]] == false && act != '0';
    final (state, c, tint) = act == '0'
        ? ('NOT INSTALLED', cIdle, cIdleTint)
        : disabled
            ? ('OFF', cHold, cHoldTint)
            : switch (v) {
                'BLOCK' || 'DENY' => ('BLOCKED', cBlock, cBlockTint),
                'PASS' || 'ALLOW' => ('PASSED', cPass, cPassTint),
                _ => ('—', cIdle, cIdleTint),
              };
    final row = Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: state == 'BLOCKED' ? cBlockTint : cIdleTint,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: state == 'BLOCKED' ? cBlock.withValues(alpha: 0.35) : Colors.transparent),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            width: 28,
            alignment: Alignment.center,
            padding: const EdgeInsets.symmetric(vertical: 3),
            decoration: BoxDecoration(color: cSurface, borderRadius: BorderRadius.circular(7), border: Border.all(color: cLine)),
            child: Text(l, style: sans(size: 11, w: FontWeight.w800, c: cInk)),
          ),
          const SizedBox(width: 10),
          Expanded(child: Text(layerNames[l]!, style: sans(size: 13, w: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis)),
          chip(state, c, tint),
        ]),
        if (ev != null && act != '0' && !disabled)
          Padding(
            padding: const EdgeInsets.only(top: 4, left: 38),
            child: Text('${ev['detail'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis, style: sans(size: 11.5, c: cMuted)),
          ),
      ]),
    );
    if (state != 'BLOCKED') return row;
    return TweenAnimationBuilder<double>(
      key: ValueKey('${l}_${ev?['title']}'),
      tween: Tween(begin: 1, end: 0),
      duration: const Duration(milliseconds: 600),
      builder: (_, x, child) => Container(
        decoration: BoxDecoration(color: cBlock.withValues(alpha: 0.35 * x), borderRadius: BorderRadius.circular(12)),
        child: child,
      ),
      child: row,
    );
  }
}

import 'dart:async';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../widgets/theme.dart';

class ApproverScreen extends StatelessWidget {
  const ApproverScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser;
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        backgroundColor: cSurface,
        title: Row(children: [
          Image.asset('assets/brand/logo.png', width: 30, height: 30),
          const SizedBox(width: 10),
          Text('Approvals', style: sans(size: 18, w: FontWeight.w600)),
        ]),
        actions: [Padding(padding: const EdgeInsets.only(right: 12), child: Center(child: Text(user?.email ?? '', style: sans(size: 12.5, c: cMuted))))],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 390),
          child: ListView(padding: const EdgeInsets.all(12), children: [
            LiveDoc('approvals', (d) => ApprovalCard(doc: d)),
            LiveDoc('baseline_confirmations', (d) => BankCard(doc: d)),
            const SizedBox(height: 8),
            const AlertsFeed(),
          ]),
        ),
      ),
    );
  }
}

/// The newest approval / bank confirmation, shown while PENDING and for 60 s after a decision, so the phone
/// (and the Mission Control mirror) can show "Approved, executing…" -> "Paid" or "Transfer sent".
bool isLive(Map<String, dynamic> d) {
  final st = d['status'];
  if (st == 'PENDING') return true;
  if (!['APPROVED', 'EXECUTED', 'CONFIRMED'].contains(st)) return false;
  final at = d['decided_at'];
  return at is! Timestamp || DateTime.now().difference(at.toDate()).inSeconds < 60; // null = write pending
}

Stream<QuerySnapshot<Map<String, dynamic>>> newest(String col) =>
    db.collection(col).orderBy('created_at', descending: true).limit(1).snapshots();

class LiveDoc extends StatefulWidget {
  final String collection;
  final Widget Function(QueryDocumentSnapshot<Map<String, dynamic>>) builder;
  final Widget fallback;
  const LiveDoc(this.collection, this.builder, {super.key, this.fallback = const SizedBox.shrink()});
  @override
  State<LiveDoc> createState() => _LiveDocState();
}

class _LiveDocState extends State<LiveDoc> {
  Timer? _t;
  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 2), (_) => setState(() {})); // re-check the 60 s window
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
        stream: newest(widget.collection),
        builder: (_, s) {
          final docs = s.data?.docs ?? const [];
          return docs.isNotEmpty && isLive(docs.first.data()) ? widget.builder(docs.first) : widget.fallback;
        },
      );
}

// ---------------------------------------------------------------- TruePay approval card
class ApprovalCard extends StatefulWidget {
  final QueryDocumentSnapshot<Map<String, dynamic>> doc;
  final bool readOnly;
  const ApprovalCard({super.key, required this.doc, this.readOnly = false});
  @override
  State<ApprovalCard> createState() => _ApprovalCardState();
}

class _ApprovalCardState extends State<ApprovalCard> {
  Timer? _t;
  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> decide(String status) async {
    final uid = FirebaseAuth.instance.currentUser!.uid;
    await widget.doc.reference.update({'status': status, 'decided_by': uid, 'decided_at': FieldValue.serverTimestamp()});
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.doc.data();
    final exp = (a['expires_at'] as Timestamp?)?.toDate();
    final left = exp == null ? 0 : exp.difference(DateTime.now()).inSeconds.clamp(0, 9999);
    final checks = (a['checks'] as List?) ?? const [];
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: card(),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('Payment approval', style: sans(size: 15, w: FontWeight.w600)),
          const Spacer(),
          if (a['status'] == 'PENDING')
            Text('${left ~/ 60}:${(left % 60).toString().padLeft(2, '0')}', style: mono(c: cHold)),
        ]),
        const SizedBox(height: 8),
        Text('${a['vendor_name']}', style: sans(w: FontWeight.w600)),
        Text('${a['invoice_no']}', style: mono(c: cMuted)),
        const SizedBox(height: 6),
        Text(euro(a['amount_cents']), style: sans(size: 36, w: FontWeight.w700)),
        Row(children: [
          Text('${a['iban_masked']}', style: mono()),
          const SizedBox(width: 8),
          Text('Matches vendor master', style: sans(size: 12.5, c: cPass, w: FontWeight.w600)),
        ]),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 4, children: [
          for (final c in checks)
            SizedBox(
              width: 160,
              child: Row(children: [
                Icon(c['pass'] == true ? Icons.check : Icons.close, size: 16, color: c['pass'] == true ? cPass : cBlock),
                const SizedBox(width: 4),
                Expanded(child: Text('${c['check']} ${c['detail']}', overflow: TextOverflow.ellipsis, style: sans(size: 12.5))),
              ]),
            ),
        ]),
        const SizedBox(height: 14),
        if (a['status'] == 'APPROVED')
          Row(children: [
            const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: cPass)),
            const SizedBox(width: 8),
            Text('Approved, executing…', style: sans(w: FontWeight.w600, c: cPass)),
          ])
        else if (a['status'] == 'EXECUTED')
          Row(children: [
            const Icon(Icons.check_circle, color: cPass),
            const SizedBox(width: 8),
            Text('Paid', style: sans(size: 18, w: FontWeight.w700, c: cPass)),
          ])
        else if (!widget.readOnly)
          Row(children: [
            Expanded(
              child: SizedBox(
                  height: 52,
                  child: OutlinedButton(
                      style: OutlinedButton.styleFrom(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
                      onPressed: () => decide('REJECTED'),
                      child: const Text('Reject'))),
            ),
            const SizedBox(width: 10),
            Expanded(
              flex: 2,
              child: SizedBox(
                  height: 52,
                  child: FilledButton(
                      style: FilledButton.styleFrom(backgroundColor: cPass, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
                      onPressed: () => decide('APPROVED'),
                      child: Text('Approve ${euro(a['amount_cents'])}', style: sans(c: cPage, w: FontWeight.w700)))),
            ),
          ]),
      ]),
    );
  }
}

// ---------------------------------------------------------------- Act 0: a generic bank app, NOT TruePay
class BankCard extends StatefulWidget {
  final QueryDocumentSnapshot<Map<String, dynamic>> doc;
  final bool readOnly;
  const BankCard({super.key, required this.doc, this.readOnly = false});
  @override
  State<BankCard> createState() => _BankCardState();
}

class _BankCardState extends State<BankCard> {
  @override
  Widget build(BuildContext context) {
    final b = widget.doc.data();
    final iban = (b['iban'] ?? '') as String;
    final grouped = iban.replaceAllMapped(RegExp(r'.{4}'), (m) => '${m[0]} ').trim();
    const grey = TextStyle(fontFamily: 'Roboto');
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8), border: Border.all(color: const Color(0xFFCCCCCC))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          padding: const EdgeInsets.all(12),
          color: const Color(0xFF5F6368),
          child: Text('Your bank', style: grey.copyWith(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w600)),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Confirm transfer', style: grey.copyWith(fontSize: 20, fontWeight: FontWeight.w600)),
            const SizedBox(height: 10),
            Text('Payee', style: grey.copyWith(color: Colors.black54, fontSize: 12.5)),
            Text('${b['payee_name']}', style: grey.copyWith(fontSize: 15)),
            const SizedBox(height: 6),
            Text('IBAN', style: grey.copyWith(color: Colors.black54, fontSize: 12.5)),
            Text(grouped, style: grey.copyWith(fontSize: 15, fontFamily: 'monospace')),
            const SizedBox(height: 6),
            Text('Amount', style: grey.copyWith(color: Colors.black54, fontSize: 12.5)),
            Text(euro(b['amount_cents']), style: grey.copyWith(fontSize: 24, fontWeight: FontWeight.w700)),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(8),
              color: const Color(0xFFFFF3C4),
              child: Text("Name check: close match, account holder 'Mueller Buerobedarf'",
                  style: grey.copyWith(fontSize: 13, color: const Color(0xFF6B5300))),
            ),
            const SizedBox(height: 14),
            if (b['status'] == 'CONFIRMED')
              Text('Transfer sent', style: grey.copyWith(fontSize: 16, fontWeight: FontWeight.w600))
            else if (!widget.readOnly)
              SizedBox(
                width: double.infinity,
                height: 48,
                child: FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: const Color(0xFF1A73E8)),
                  onPressed: () async {
                    await widget.doc.reference.update({'status': 'CONFIRMED', 'decided_at': FieldValue.serverTimestamp()});
                  },
                  child: const Text('Confirm with TAN'),
                ),
              ),
          ]),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------------- alerts feed
class AlertsFeed extends StatelessWidget {
  const AlertsFeed({super.key});
  @override
  Widget build(BuildContext context) => StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
        // ponytail: newest 50 events filtered client-side; avoids a (type, ts) composite index
        stream: db.collection('events').orderBy('ts', descending: true).limit(50).snapshots(),
        builder: (_, s) {
          final alerts = (s.data?.docs ?? []).map((d) => d.data()).where((e) => e['type'] == 'ALERT').take(5).toList();
          if (alerts.isEmpty) {
            return Padding(
                padding: const EdgeInsets.all(16),
                child: Center(child: Text('All clear. No payments waiting.', style: sans(c: cMuted))));
          }
          return Column(children: [
            for (final e in alerts)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(12),
                decoration: card(color: cBlockTint, border: cBlock, r: 10),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(child: Text('${e['title']}', style: sans(w: FontWeight.w600, c: cBlock))),
                    Text(hms(e['ts']), style: mono(size: 12.5, c: cMuted)),
                  ]),
                  Text('${e['detail']}', style: sans(size: 13)),
                ]),
              ),
          ]);
        },
      );
}

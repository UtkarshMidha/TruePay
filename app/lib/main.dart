import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_web_plugins/url_strategy.dart';

import 'screens/approver.dart';
import 'screens/mission_control.dart';
import 'screens/report.dart';
import 'widgets/theme.dart';

// Firebase web config via --dart-define-from-file=firebase.web.json (see Makefile `web`).
// Local dev without keys: --dart-define=EMULATOR=true (Firestore :8085, Auth :9099, project demo-truepay).
const _emulator = bool.fromEnvironment('EMULATOR');
const _opts = FirebaseOptions(
  apiKey: String.fromEnvironment('apiKey', defaultValue: 'demo-key'),
  appId: String.fromEnvironment('appId', defaultValue: '1:0:web:0'),
  messagingSenderId: String.fromEnvironment('messagingSenderId', defaultValue: '0'),
  projectId: String.fromEnvironment('projectId', defaultValue: 'demo-truepay'),
  authDomain: String.fromEnvironment('authDomain'),
  storageBucket: String.fromEnvironment('storageBucket'),
);

// Demo accounts: no login page. The route picks the identity (Firestore rules still check it):
//   /approve -> approver, everything else -> operator. Passwords come from the git-ignored
//   demo_accounts.json via --dart-define-from-file (emulator: demo1234).
const _operatorPw = String.fromEnvironment('OPERATOR_PASSWORD', defaultValue: 'demo1234');
const _approverPw = String.fromEnvironment('APPROVER_PASSWORD', defaultValue: 'demo1234');

Future<void> main() async {
  usePathUrlStrategy(); // /approve and /report as real paths (Hosting rewrites to index.html)
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: _opts);
  if (_emulator) {
    FirebaseFirestore.instance.useFirestoreEmulator('localhost', 8085);
    await FirebaseAuth.instance.useAuthEmulator('localhost', 9099);
  }
  // Per-tab session, so the operator tab and an /approve tab on the same laptop keep their own identity.
  await FirebaseAuth.instance.setPersistence(Persistence.SESSION);
  final approver = Uri.base.path.startsWith('/approve');
  String? error;
  try {
    await FirebaseAuth.instance.signInWithEmailAndPassword(
        email: approver ? 'approver@iw-demo.example' : 'operator@iw-demo.example',
        password: approver ? _approverPw : _operatorPw);
  } on FirebaseAuthException catch (e) {
    error = e.code;
  }
  runApp(App(error: error));
}

class App extends StatelessWidget {
  final String? error;
  const App({super.key, this.error});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'TruePay',
        debugShowCheckedModeBanner: false,
        theme: appTheme(),
        onGenerateRoute: (s) => MaterialPageRoute(
          settings: s,
          builder: (_) => error != null
              ? Scaffold(body: Center(child: Text('Demo sign-in failed: $error', style: sans(c: cBlock))))
              : switch (s.name) {
                  '/approve' => const ApproverScreen(),
                  '/report' => const ReportScreen(),
                  _ => const MissionControl(),
                },
        ),
      );
}

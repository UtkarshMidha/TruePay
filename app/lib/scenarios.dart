// Mirrors SCENARIOS in backend/common/config.py (PRD §3). Keys are a frozen contract.

class Scenario {
  final String act; // '0'..'5' or 'judge'
  final String key; // command `scenario` value
  final String? fixture;
  final String button;
  final String title;
  final String subtitle;
  final String switches; // 'ignored' | 'defaults' | 'L1-L3 off, jailbreak on' | 'as set'
  const Scenario(this.act, this.key, this.fixture, this.button, this.title, this.subtitle, this.switches);
}

const scenarios = <Scenario>[
  Scenario('0', 'baseline', 'INV-1003', 'legacy', 'Legacy AP automation', 'INV-1003 · €18,950 · no controls', 'ignored'),
  Scenario('1', 'clean', 'INV-1001', 'clean', 'Standard invoice', 'INV-1001 · €4,280 · Müller Bürobedarf', 'defaults'),
  Scenario('2', 'poisoned', 'INV-1002', 'inject', 'Prompt injection', 'INV-1002 · hidden text in the PDF', 'defaults'),
  Scenario('3', 'swap', 'INV-1003', 'swap', 'IBAN substitution', 'INV-1003 · new bank details', 'defaults'),
  Scenario('4', 'insider', null, 'insider', 'Compromised service', 'Onboarding identity misuse', 'ignored'),
  Scenario('5', 'poisoned', 'INV-1002', 'jailbreak', 'Jailbroken controller', 'L1–L3 off · firewall only', 'L1-L3 off, jailbreak on'),
  Scenario('judge', 'judge', 'INV-1099', 'custom', 'Custom invoice', 'INV-1099', 'as set'),
];

/// The five scenario buttons in the left rail (Act 5 reuses button 2 with switches).
final scenarioButtons = scenarios.where((s) => ['0', '1', '2', '3', '4', '5'].contains(s.act)).toList();

const breachLayers = {'hidden_text': false, 'model_armor': false, 'quarantine': false, 'jailbreak_controller': true};
const defaultLayers = {'hidden_text': true, 'model_armor': true, 'quarantine': true, 'jailbreak_controller': false};

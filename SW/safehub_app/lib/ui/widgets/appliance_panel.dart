import 'package:flutter/material.dart';

import '../../core/appliance_controls.dart';
import '../../services/shortcut_store.dart';

/// No hardware commands are published. Hub commands are observed by the parent.
class AppliancePanel extends StatefulWidget {
  final ApplianceControls controls;
  final bool connected;
  final String latestSign;
  final ShortcutStore? store;
  final bool loadShortcuts;

  const AppliancePanel(
      {super.key,
      required this.controls,
      required this.connected,
      required this.latestSign,
      this.store,
      this.loadShortcuts = true});
  @override
  State<AppliancePanel> createState() => _AppliancePanelState();
}

class _AppliancePanelState extends State<AppliancePanel> {
  final _sign = TextEditingController();
  String _device = 'aircon';
  String _action = 'toggle';
  String? _editing;
  String? _json;
  String _message = '';
  bool _loading = true;
  bool _saving = false;
  bool _preview = true;
  ShortcutStore? _store;
  ApplianceControls get model => widget.controls;

  @override
  void initState() {
    super.initState();

    if (widget.loadShortcuts) {
      _load();
    } else {
      _loading = false;
    }
  }

  Future<void> _load() async {
    try {
      _store = widget.store ?? ShortcutStore.forApp();
      final source = await _store!.read();
      if (!mounted) return;
      if (source != null) model.restore(source);
    } catch (_) {
      _message = '저장된 단축키를 읽지 못했습니다. 기존 파일은 유지됩니다.';
      _store = null; // Do not overwrite unreadable data.
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _persist(VoidCallback mutation, String success) async {
    if (_saving || _loading || _store == null) return;
    final before = model.encode();
    setState(() => _saving = true);
    try {
      mutation();
      await _store!.write(model.encode());
      if (mounted) setState(() => _message = success);
    } catch (_) {
      model.restore(before);
      if (mounted) setState(() => _message = '저장 실패: 변경을 취소했습니다.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _register() async {
    final sign = _sign.text.trim();
    if (sign.isEmpty) {
      setState(() => _message = '수어 이름을 입력하거나 최근 인식 결과를 선택하세요.');
      return;
    }
    if (model.bindings.containsKey(sign) && _editing != sign) {
      setState(() => _message = '이미 등록된 수어입니다. 목록에서 수정하세요.');
      return;
    }
    final binding = SignBinding(sign: sign, device: _device, action: _action);
    await _persist(() {
      if (_editing != null) model.bindings.remove(_editing);
      model.register(binding);
    }, '앱에 저장했습니다 · 허브 등록은 아직 미연동');
  }

  @override
  void dispose() {
    _sign.dispose();
    super.dispose();
  }

  Widget _card(Widget child) => Container(
        padding: const EdgeInsets.all(22),
        decoration: BoxDecoration(
            color: const Color(0xFF242D33),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: const Color(0xFF43515B))),
        child: child,
      );

  String _actionLabel(String device, String action) => device == 'curtain'
      ? {'on': '열기', 'off': '닫기', 'toggle': '열기/닫기 전환'}[action]!
      : ApplianceControls.actions[action]!;

  Widget _deviceCard(String id, String label) {
    final bool? state = _preview
        ? model.preview[id]
        : id == 'aircon'
            ? model.hubAirconPower
            : null;
    final status = state == null
        ? '상태 미확인'
        : id == 'curtain'
            ? (state ? '열림' : '닫힘')
            : (state ? '켜짐 · ON' : '꺼짐 · OFF');
    return _card(
        Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Icon(
          id == 'aircon'
              ? Icons.ac_unit
              : id == 'light'
                  ? Icons.lightbulb_outline
                  : Icons.curtains,
          size: 30,
          color: const Color(0xFFBADBCF)),
      const SizedBox(height: 12),
      Text('거실 $label',
          style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w600)),
      const SizedBox(height: 10),
      Semantics(
          liveRegion: true,
          child: Text(status, style: const TextStyle(fontSize: 23))),
      const SizedBox(height: 8),
      Text(_preview ? '시뮬레이션 상태' : '최근 허브 명령 · 실제 기기 상태 아님',
          style: const TextStyle(fontSize: 13, color: Color(0xFFB7C3CA))),
      const SizedBox(height: 16),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final action in ['on', 'off'])
          OutlinedButton(
              onPressed: _preview
                  ? () => setState(() => model.applyPreview(id, action))
                  : null,
              child: Text(_actionLabel(id, action))),
      ]),
    ]));
  }

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: Theme.of(context).copyWith(
          brightness: Brightness.dark,
          colorScheme: const ColorScheme.dark(
              primary: Color(0xFFBADBCF), surface: Color(0xFF242D33)),
          textTheme: Theme.of(context).textTheme.apply(
              bodyColor: const Color(0xFFF1F5F6),
              displayColor: const Color(0xFFF1F5F6)),
          inputDecorationTheme:
              const InputDecorationTheme(border: OutlineInputBorder())),
      child: SingleChildScrollView(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _card(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('거실 기기 & 수어 단축키',
              style: TextStyle(fontSize: 28, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          const Text('버튼 테스트와 허브 명령 확인을 분리했습니다. 실제 가전은 작동하지 않습니다.'),
          SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('시뮬레이션 모드'),
              subtitle: Text(
                  _preview ? '버튼과 단축키를 앱 안에서 테스트' : '허브 명령 보기 전용 · 버튼 제어 미연동'),
              value: _preview,
              onChanged: (value) => setState(() => _preview = value)),
          Text(widget.connected
              ? 'MQTT 연결됨'
              : 'MQTT 끊김 · 이전 명령은 최신 상태가 아닐 수 있습니다.'),
          if (!_preview && model.hubCommandAt != null)
            Text('최근 수신: ${model.hubCommandAt!.toLocal()}'),
        ])),
        const SizedBox(height: 18),
        LayoutBuilder(
            builder: (context, bounds) =>
                Wrap(spacing: 16, runSpacing: 16, children: [
                  for (final entry in ApplianceControls.devices.entries)
                    SizedBox(
                        width: bounds.maxWidth >= 800
                            ? (bounds.maxWidth - 32) / 3
                            : bounds.maxWidth,
                        child: _deviceCard(entry.key, entry.value))
                ])),
        const SizedBox(height: 18),
        _card(Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(_editing == null ? '수어 단축키 등록' : '수어 단축키 수정',
              style:
                  const TextStyle(fontSize: 23, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          const Text('수어 이름은 인식 결과와 정확히 같아야 합니다. 현재 공간은 거실만 지원합니다.'),
          const SizedBox(height: 16),
          TextField(
              controller: _sign,
              enabled: !_saving && !_loading,
              decoration: const InputDecoration(
                  labelText: '수어 이름', hintText: '예: 에어컨')),
          if (widget.latestSign != '수어 인식 대기 중' &&
              widget.latestSign.trim().isNotEmpty)
            TextButton(
                onPressed: _saving
                    ? null
                    : () =>
                        setState(() => _sign.text = widget.latestSign.trim()),
                child: Text('최근 인식 결과 사용: ${widget.latestSign}')),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
              value: 'livingroom',
              decoration: const InputDecoration(labelText: '공간'),
              items: const [
                DropdownMenuItem(value: 'livingroom', child: Text('거실'))
              ],
              onChanged: _saving ? null : (_) {}),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
              value: _device,
              decoration: const InputDecoration(labelText: '기기'),
              items: [
                for (final e in ApplianceControls.devices.entries)
                  DropdownMenuItem(value: e.key, child: Text(e.value))
              ],
              onChanged: _saving ? null : (v) => setState(() => _device = v!)),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
              value: _action,
              decoration: const InputDecoration(labelText: '동작'),
              items: [
                for (final id in ApplianceControls.actions.keys)
                  DropdownMenuItem(
                      value: id, child: Text(_actionLabel(_device, id)))
              ],
              onChanged: _saving ? null : (v) => setState(() => _action = v!)),
          const SizedBox(height: 16),
          Wrap(spacing: 12, children: [
            FilledButton(
                onPressed:
                    _loading || _saving || _store == null ? null : _register,
                child: Text(_saving
                    ? '저장 중'
                    : _editing == null
                        ? '앱에 등록'
                        : '수정 저장')),
            if (_editing != null)
              TextButton(
                  onPressed: _saving
                      ? null
                      : () => setState(() {
                            _editing = null;
                            _sign.clear();
                          }),
                  child: const Text('수정 취소')),
          ]),
          if (_loading) const LinearProgressIndicator(),
          if (_message.isNotEmpty)
            Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Semantics(liveRegion: true, child: Text(_message))),
        ])),
        const SizedBox(height: 18),
        _card(Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('등록한 단축키',
              style: TextStyle(fontSize: 23, fontWeight: FontWeight.w600)),
          const Text('앱 로컬 목록 · 허브 등록 확인 기능은 아직 연결되지 않았습니다.'),
          if (model.bindings.isEmpty)
            const Padding(
                padding: EdgeInsets.all(20), child: Text('등록한 단축키가 없습니다.')),
          for (final b in model.bindings.values)
            Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                          '${b.sign} → 거실 ${ApplianceControls.devices[b.device]} → ${_actionLabel(b.device, b.action)}',
                          style: const TextStyle(
                              fontSize: 18, fontWeight: FontWeight.w600)),
                      Text(b.hubSupported
                          ? '학진이 V1 지원 형식 · 아직 미전송'
                          : 'UI 테스트 전용 · 허브 동작 확장 필요'),
                      Wrap(spacing: 8, runSpacing: 4, children: [
                        TextButton(
                            onPressed: _saving
                                ? null
                                : () => setState(() {
                                      _editing = b.sign;
                                      _sign.text = b.sign;
                                      _device = b.device;
                                      _action = b.action;
                                      _message = '위 등록 양식에서 수정하세요.';
                                    }),
                            child: const Text('수정')),
                        TextButton(
                            onPressed: _saving || _store == null
                                ? null
                                : () async {
                                    await _persist(
                                        () => model.bindings.remove(b.sign),
                                        '앱에서 삭제했습니다 · 허브에는 미전송');
                                    if (mounted)
                                      setState(() {
                                        _editing = null;
                                        _sign.clear();
                                      });
                                  },
                            child: const Text('삭제')),
                        TextButton(
                            onPressed: _preview
                                ? () =>
                                    setState(() => model.simulateSign(b.sign))
                                : null,
                            child: const Text('단축키 테스트')),
                        TextButton(
                            onPressed: () =>
                                setState(() => _json = b.registrationPayload()),
                            child: const Text('등록 JSON')),
                        TextButton(
                            onPressed: () =>
                                setState(() => _json = b.removalPayload()),
                            child: const Text('삭제 JSON')),
                      ]),
                    ])),
          if (_json != null) ...[
            const Divider(),
            const Text('허브 연동용 JSON · 자동 전송되지 않음'),
            SelectableText(_json!),
            TextButton(
                onPressed: () => setState(() => _json = null),
                child: const Text('접기')),
          ],
        ])),
      ])),
    );
  }
}

import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../config/app_config.dart';
import '../core/alert_coordinator.dart';
import '../core/event_manager.dart';
import '../mqtt/mqtt_receiver.dart';
import '../services/audio_service.dart';
import '../services/camera_stream_service.dart';
import '../services/disaster_service.dart';
import '../services/tts_service.dart';
import 'utils/disaster_display.dart';
import 'widgets/disaster_overlay.dart';

enum _SafeHubPage {
  home,
  signTranslation,
}

class SafeHubHomePage extends StatefulWidget {
  const SafeHubHomePage({super.key});

  @override
  State<SafeHubHomePage> createState() => _SafeHubHomePageState();
}

class _SafeHubHomePageState extends State<SafeHubHomePage>
    with SingleTickerProviderStateMixin {
  final EventManager _eventManager = EventManager();
  final DisasterService _disasterService = DisasterService();
  final AlertCoordinator _alertCoordinator = AlertCoordinator();
  final AudioService _audioService = AudioService();

  late final MqttReceiver _mqttReceiver;
  late final AnimationController _alertPulseController;
  late final TtsService _ttsService;
  final CameraStreamService _cameraStreamService = CameraStreamService();

  Timer? _disasterTimer;

  _SafeHubPage _currentPage = _SafeHubPage.home;

  bool _mqttConnected = false;
  String _connectionStatus = '연결 중';
  String _signText = '수어 인식 대기 중';
  String _ttsStatus = '음성 안내 대기';

  static const int _cameraWidth = 320;
  static const int _cameraHeight = 240;

  ui.Image? _cameraImage;
  bool _cameraConnected = false;

  Map<String, dynamic>? _latestDisaster;

  int? _lastDisasterSn;
  int _speechGeneration = 0;

  final List<Map<String, dynamic>> _recentEvents = [];

  @override
  void initState() {
    super.initState();

    _alertPulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );

    _ttsService = TtsService(
      baseUrl: AppConfig.ttsServerUrl,
    );

    _mqttReceiver = MqttReceiver(
      broker: AppConfig.mqttBroker,
      port: AppConfig.mqttPort,
      eventManager: _eventManager,
      onEventReceived: _handleEvent,
      onSignTextReceived: _handleSignText,
      onConnectionChanged: _handleConnectionChanged,
    );

    _connectMqtt();
    _connectCamera();
    _startDisasterPolling();
  }

  void _connectCamera() {
    unawaited(
      _cameraStreamService.connect(
        host: AppConfig.cameraHost,
        port: AppConfig.cameraPort,
        onFrame: _handleCameraFrame,
        onConnectionChanged: (connected) {
          if (!mounted) {
            return;
          }

          final previousImage = connected ? null : _cameraImage;

          setState(() {
            _cameraConnected = connected;

            if (!connected) {
              _cameraImage = null;
            }
          });

          previousImage?.dispose();
        },
      ),
    );
  }

  void _handleCameraFrame(Uint8List frame) {
    const expectedBytes = _cameraWidth * _cameraHeight * 4;

    if (frame.lengthInBytes != expectedBytes) {
      return;
    }

    ui.decodeImageFromPixels(
      frame,
      _cameraWidth,
      _cameraHeight,
      ui.PixelFormat.rgba8888,
      (image) {
        if (!mounted) {
          image.dispose();
          return;
        }

        final previousImage = _cameraImage;

        setState(() {
          _cameraImage = image;
        });

        previousImage?.dispose();
      },
    );
  }

  void _startDisasterPolling() {
    _fetchLatestDisaster();

    _disasterTimer = Timer.periodic(
      const Duration(minutes: 2),
      (_) {
        _fetchLatestDisaster();
      },
    );
  }

  Future<void> _fetchLatestDisaster() async {
    try {
      final disaster = await _disasterService.fetchLatest();

      if (disaster == null || !mounted) {
        return;
      }

      final sn = disaster['SN'];

      if (sn is! int || _lastDisasterSn == sn) {
        return;
      }

      final isInitialLoad = _lastDisasterSn == null;
      final disasterData = Map<String, dynamic>.from(disaster);
      final severity = getDisasterSeverity(disasterData);

      var activated = false;

      if (!isInitialLoad && severity != DisasterSeverity.notice) {
        activated = _alertCoordinator.submit(
          SafeHubAlert(
            kind: AlertKind.disaster,
            priority: _getDisasterPriority(severity),
            data: disasterData,
          ),
        );
      }

      setState(() {
        _lastDisasterSn = sn;
        _latestDisaster = disasterData;
      });

      if (activated) {
        _interruptNormalSpeech();
        _restartAlertPulse();
      }
    } catch (e, st) {
      debugPrint('[재난 API 실패] $e');
      debugPrint('$st');
      // 재난 API 실패 시 다른 SafeHub 기능은 계속 동작한다.
    }
  }

  int _getDisasterPriority(DisasterSeverity severity) {
    switch (severity) {
      case DisasterSeverity.notice:
        return 3;
      case DisasterSeverity.emergency:
        return 6;
      case DisasterSeverity.critical:
        return 8;
    }
  }

  Future<void> _connectMqtt() async {
    try {
      await _mqttReceiver.connect();

      if (!mounted) {
        return;
      }

      setState(() {
        _mqttConnected = true;
        _connectionStatus = '연결됨';
      });
    } catch (_) {
      if (!mounted) {
        return;
      }

      setState(() {
        _mqttConnected = false;
        _connectionStatus = '연결 실패';
      });
    }
  }

  void _handleConnectionChanged(bool connected) {
    if (!mounted) {
      return;
    }

    setState(() {
      _mqttConnected = connected;
      _connectionStatus = connected ? '연결됨' : '재연결 중';
    });
  }

  void _handleSignText(String text) {
    if (!mounted) {
      return;
    }

    final cleanText = text.trim();

    if (cleanText.isEmpty) {
      return;
    }

    setState(() {
      _signText = cleanText;
      _ttsStatus =
          AppConfig.ttsServerUrl.trim().isEmpty ? '텍스트로 표시됨' : '음성 변환 준비 중';
    });

    final generation = ++_speechGeneration;

    unawaited(
      _speakTranslation(
        cleanText,
        generation,
      ),
    );
  }

  Future<void> _speakTranslation(
    String text,
    int generation,
  ) async {
    if (AppConfig.ttsServerUrl.trim().isEmpty) {
      return;
    }

    if (_alertCoordinator.hasActiveAlert) {
      return;
    }

    try {
      if (mounted) {
        setState(() {
          _ttsStatus = '음성 안내 준비 중';
        });
      }

      await _audioService.stop();

      if (generation != _speechGeneration || _alertCoordinator.hasActiveAlert) {
        return;
      }

      final bytes = await _ttsService.synthesize(text);

      if (!mounted ||
          generation != _speechGeneration ||
          _alertCoordinator.hasActiveAlert) {
        return;
      }

      setState(() {
        _ttsStatus = '음성 안내 중';
      });

      await _audioService.playBytes(bytes);

      if (mounted &&
          generation == _speechGeneration &&
          !_alertCoordinator.hasActiveAlert) {
        setState(() {
          _ttsStatus = '음성으로 전달됨';
        });
      }
    } catch (_) {
      if (mounted && generation == _speechGeneration) {
        setState(() {
          _ttsStatus = '텍스트 번역은 정상 표시 중';
        });
      }
    }
  }

  void _handleEvent(Map<String, dynamic> event) {
    if (!mounted) {
      return;
    }

    final eventData = Map<String, dynamic>.from(event);
    eventData['_receivedAt'] ??= DateTime.now().toIso8601String();

    var activated = false;

    if (_isEmergencyEvent(eventData)) {
      activated = _alertCoordinator.submit(
        SafeHubAlert(
          kind: AlertKind.fall,
          priority: _getEventPriority(eventData),
          data: eventData,
        ),
      );
    }

    setState(() {
      _recentEvents.insert(
        0,
        eventData,
      );

      if (_recentEvents.length > 5) {
        _recentEvents.removeLast();
      }
    });

    if (activated) {
      _interruptNormalSpeech();
      _restartAlertPulse();
    }
  }

  int _getEventPriority(Map<String, dynamic> event) {
    final priority = event['priority'];

    if (priority is int && priority >= 1 && priority <= 10) {
      return priority;
    }

    return 9;
  }

  bool _isEmergencyEvent(Map<String, dynamic> event) {
    return event['event'] == 'fall_detected';
  }

  void _interruptNormalSpeech() {
    _speechGeneration++;
    unawaited(_audioService.stop());

    if (mounted) {
      setState(() {
        _ttsStatus = '안전 알림으로 음성 안내 중단';
      });
    }
  }

  void _acknowledgeActiveAlert() {
    _alertCoordinator.acknowledgeCurrent();

    setState(() {});

    _syncAlertPulse();
  }

  void _restartAlertPulse() {
    _alertPulseController
      ..stop()
      ..reset()
      ..repeat(reverse: true);
  }

  void _syncAlertPulse() {
    if (_alertCoordinator.hasActiveAlert) {
      _restartAlertPulse();
      return;
    }

    _alertPulseController
      ..stop()
      ..reset();
  }

  void _openSignTranslation() {
    if (_currentPage == _SafeHubPage.signTranslation) {
      return;
    }

    setState(() {
      _currentPage = _SafeHubPage.signTranslation;
    });
  }

  void _returnHome() {
    if (_currentPage == _SafeHubPage.home) {
      return;
    }

    setState(() {
      _currentPage = _SafeHubPage.home;
    });
  }

  @override
  void dispose() {
    _disasterTimer?.cancel();
    _speechGeneration++;
    unawaited(_audioService.dispose());
    unawaited(_cameraStreamService.dispose());
    _cameraImage?.dispose();
    _cameraImage = null;
    _alertPulseController.dispose();
    _mqttReceiver.disconnect();
    super.dispose();
  }

  // SafeHub glass layout v4 — presentation only.
  static const _ink = Color(0xFFF3F1EE);
  static const _muted = Color(0xFFC4C1BD);
  static const _blue = Color(0xFFB9D2FA);
  static const _green = Color(0xFFA5DDAA);
  static const _amber = Color(0xFFF3D49B);
  String _selectedRoom = 'all';
  String? _detailTitle;
  String _detailBody = '';

  Text _text(String value,
          {double size = 18,
          Color color = _ink,
          FontWeight weight = FontWeight.w500,
          int lines = 1}) =>
      Text(value,
          maxLines: lines,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
              fontSize: size,
              color: color,
              fontWeight: weight,
              height: 1.3,
              letterSpacing: -0.3));

  @override
  Widget build(BuildContext context) {
    final activeAlert = _alertCoordinator.activeAlert;
    return Scaffold(
      backgroundColor: const Color(0xFF24221F),
      body: Stack(children: [
        Positioned.fill(
            child: Image.asset(
          'assets/images/safehub_living_room.png',
          fit: BoxFit.cover,
          errorBuilder: (context, error, stackTrace) =>
              const ColoredBox(color: Color(0xFF393731)),
        )),
        const Positioned.fill(
            child: DecoratedBox(
                decoration: BoxDecoration(
          gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Color(0x66201D19),
                Color(0x33201D19),
                Color(0x88201D19),
              ]),
        ))),
        SafeArea(
            child: Padding(
          padding: const EdgeInsets.fromLTRB(34, 22, 34, 30),
          child: Column(children: [
            _glassHeader(),
            const SizedBox(height: 24),
            Expanded(
                child: _currentPage == _SafeHubPage.home
                    ? _glassDashboard(activeAlert)
                    : _glassTranslation()),
          ]),
        )),
        if (_detailTitle != null)
          Positioned.fill(
              child: ColoredBox(
            color: const Color(0x99000000),
            child: Center(
                child: Container(
              constraints: BoxConstraints(
                  maxWidth:
                      math.min(680, MediaQuery.sizeOf(context).width - 32),
                  maxHeight: MediaQuery.sizeOf(context).height * 0.8),
              child: _glass(
                  child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                    _text(_detailTitle!, size: 24, weight: FontWeight.w600),
                    const SizedBox(height: 20),
                    Flexible(
                        child: SingleChildScrollView(
                            child: Text(_detailBody,
                                style: const TextStyle(
                                    color: _ink, fontSize: 20, height: 1.5)))),
                    const SizedBox(height: 20),
                    _action('닫기', Icons.close,
                        () => setState(() => _detailTitle = null)),
                  ])),
            )),
          )),
        if (activeAlert != null && activeAlert.kind == AlertKind.fall)
          _buildFallOverlay(activeAlert.data),
        if (activeAlert != null && activeAlert.kind == AlertKind.disaster)
          DisasterOverlay(
              disaster: activeAlert.data,
              pulseAnimation: _alertPulseController,
              onAcknowledge: _acknowledgeActiveAlert),
      ]),
    );
  }

  Widget _glass(
          {required Widget child,
          bool inset = false,
          EdgeInsets padding = const EdgeInsets.all(24)}) =>
      Container(
          padding: padding,
          decoration: BoxDecoration(
            gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: inset
                    ? const [Color(0x24FFFFFF), Color(0x10FFFFFF)]
                    : const [Color(0xDB343432), Color(0xD0232423)]),
            borderRadius: BorderRadius.circular(inset ? 15 : 20),
            border: Border.all(
                color:
                    inset ? const Color(0x24FFFFFF) : const Color(0x40FFFFFF)),
            boxShadow: inset
                ? null
                : const [
                    BoxShadow(
                        color: Color(0x26000000),
                        blurRadius: 20,
                        offset: Offset(0, 8)),
                  ],
          ),
          child: child);

  Widget _heading(IconData icon, String title, {Widget? trailing}) =>
      Row(children: [
        Icon(icon, color: _ink, size: 25),
        const SizedBox(width: 12),
        Expanded(child: _text(title, size: 22, weight: FontWeight.w600)),
        if (trailing != null) trailing,
      ]);

  Widget _dot(String label, Color color) =>
      Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: color,
                boxShadow: [
                  BoxShadow(color: color.withAlpha(55), blurRadius: 8)
                ])),
        const SizedBox(width: 8),
        _text(label, color: color, size: 16),
      ]);

  Widget _glassHeader() => SizedBox(
      height: 70,
      child: Row(children: [
        const Icon(Icons.home_rounded, color: _blue, size: 48),
        const SizedBox(width: 12),
        Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _text('SafeHub', size: 31, color: _blue, weight: FontWeight.w700),
              _text('배리어프리 스마트홈', size: 15, color: _muted),
            ]),
        const Spacer(),
        if (_currentPage == _SafeHubPage.home)
          _glass(
              padding: const EdgeInsets.all(5),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                _roomTab('all', '전체', Icons.grid_view_rounded),
                _roomTab('livingroom', '거실', Icons.weekend_outlined),
                _roomTab('bedroom', '침실', Icons.bed_outlined),
                _roomTab('bathroom', '화장실', Icons.bathroom_outlined),
              ]))
        else
          _action('홈으로', Icons.home_outlined, _returnHome),
        const Spacer(),
        StreamBuilder<DateTime>(
            stream: Stream<DateTime>.periodic(
                const Duration(seconds: 1), (_) => DateTime.now()),
            initialData: DateTime.now(),
            builder: (context, snapshot) {
              final now = snapshot.data!;
              final hh = now.hour.toString().padLeft(2, '0');
              final mm = now.minute.toString().padLeft(2, '0');
              final date = now.year.toString() +
                  '.' +
                  now.month.toString().padLeft(2, '0') +
                  '.' +
                  now.day.toString().padLeft(2, '0');
              return Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _text(date, size: 14, color: _muted),
                    _text('$hh:$mm', size: 30, weight: FontWeight.w600),
                  ]);
            }),
        const SizedBox(width: 30),
        Icon(_mqttConnected ? Icons.wifi : Icons.wifi_off,
            color: _mqttConnected ? _blue : _amber, size: 30),
        const SizedBox(width: 12),
        Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _text('MQTT', size: 14, color: _muted),
              const SizedBox(height: 4),
              _dot(_connectionStatus, _mqttConnected ? _green : _amber),
            ]),
      ]));

  Widget _roomTab(String id, String label, IconData icon) {
    final selected = _selectedRoom == id;
    return Semantics(
        selected: selected,
        button: true,
        child: InkWell(
          onTap: () => setState(() => _selectedRoom = id),
          borderRadius: BorderRadius.circular(12),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
            decoration: BoxDecoration(
                color: selected ? const Color(0x556F8FAE) : Colors.transparent,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                    color: selected
                        ? const Color(0xFF9EBDE7)
                        : Colors.transparent)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(icon, size: 19, color: selected ? _blue : _muted),
              const SizedBox(width: 8),
              _text(label, size: 16, color: selected ? _ink : _muted),
            ]),
          ),
        ));
  }

  Widget _glassDashboard(SafeHubAlert? alert) =>
      Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(flex: 34, child: _signPanel()),
        const SizedBox(width: 20),
        Expanded(
            flex: 35,
            child: Column(children: [
              Expanded(flex: 6, child: _spacePanel(alert)),
              const SizedBox(height: 20),
              Expanded(flex: 4, child: _disasterPanel()),
            ])),
        const SizedBox(width: 20),
        Expanded(
            flex: 31,
            child: Column(children: [
              Expanded(flex: 6, child: _alarmPanel(alert)),
              const SizedBox(height: 20),
              Expanded(flex: 4, child: _eventsPanel()),
            ])),
      ]);

  Widget _signPanel() {
    final hasResult = _signText != '수어 인식 대기 중';
    return _glass(
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _heading(Icons.sign_language_outlined, '수어 인식'),
      const SizedBox(height: 18),
      Expanded(flex: 5, child: _cameraPlaceholder()),
      const SizedBox(height: 18),
      Expanded(
          flex: 3,
          child: _glass(
              inset: true,
              padding: const EdgeInsets.all(18),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _text('인식된 수어', size: 16, color: _muted),
                    const SizedBox(height: 8),
                    Expanded(
                        child: Align(
                            alignment: Alignment.centerLeft,
                            child: _translationText(hasResult ? 46 : 28))),
                  ]))),
      const SizedBox(height: 16),
      Row(children: [
        const Icon(Icons.volume_up_outlined, color: _muted, size: 21),
        const SizedBox(width: 10),
        Expanded(
            child: _text(_ttsStatus,
                size: 16, color: _ttsStatus == '음성으로 전달됨' ? _green : _muted)),
      ]),
      const SizedBox(height: 18),
      _action('번역 화면 열기', Icons.arrow_forward_rounded, _openSignTranslation,
          primary: true),
    ]));
  }

  Widget _cameraPlaceholder() => Container(
        width: double.infinity,
        decoration: BoxDecoration(
          color: const Color(0x88202020),
          borderRadius: BorderRadius.circular(15),
          border: Border.all(color: const Color(0x24FFFFFF)),
        ),
        clipBehavior: Clip.antiAlias,
        child: _cameraImage == null
            ? Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.videocam_outlined,
                    size: 66,
                    color: _blue,
                  ),
                  const SizedBox(height: 14),
                  _text(
                    '수어 카메라',
                    size: 23,
                    weight: FontWeight.w600,
                  ),
                  const SizedBox(height: 8),
                  _text(
                    _cameraConnected ? '카메라 영상 수신 대기 중' : 'RPi4 카메라 연결 대기 중',
                    size: 15,
                    color: _muted,
                  ),
                ],
              )
            : Stack(
                fit: StackFit.expand,
                children: [
                  RawImage(
                    image: _cameraImage,
                    fit: BoxFit.cover,
                    filterQuality: FilterQuality.low,
                  ),
                  Positioned(
                    top: 12,
                    left: 12,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xAA111111),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.circle,
                            size: 9,
                            color: _cameraConnected ? _green : _amber,
                          ),
                          const SizedBox(width: 7),
                          _text(
                            _cameraConnected ? 'LIVE' : '연결 확인',
                            size: 13,
                            color: _ink,
                            weight: FontWeight.w600,
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
      );

  Widget _translationText(double size) => AnimatedSwitcher(
      duration: const Duration(milliseconds: 250),
      child: Text(_signText,
          key: ValueKey(_signText),
          maxLines: 3,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
              fontSize: size,
              color: _blue,
              height: 1.2,
              fontWeight: FontWeight.w700,
              letterSpacing: -1)));

  Widget _action(String label, IconData icon, VoidCallback onTap,
          {bool primary = false}) =>
      SizedBox(
          height: 55,
          child: TextButton(
            onPressed: onTap,
            style: TextButton.styleFrom(
                foregroundColor: primary ? const Color(0xFF202D3E) : _ink,
                backgroundColor: primary ? _blue : const Color(0x22FFFFFF),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
                padding: const EdgeInsets.symmetric(horizontal: 20)),
            child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(label,
                      style: const TextStyle(
                          fontSize: 18, fontWeight: FontWeight.w600)),
                  const SizedBox(width: 12),
                  Icon(icon, size: 22),
                ]),
          ));

  Widget _spacePanel(SafeHubAlert? alert) {
    final rooms = <(String, String, IconData)>[
      ('bedroom', '침실', Icons.bed_outlined),
      ('bathroom', '화장실', Icons.bathroom_outlined),
      ('livingroom', '거실', Icons.weekend_outlined),
    ]
        .where((room) => _selectedRoom == 'all' || _selectedRoom == room.$1)
        .toList();
    return _glass(
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _heading(Icons.sensors_outlined, '공간별 상태'),
      const SizedBox(height: 18),
      for (var i = 0; i < rooms.length; i++) ...[
        Expanded(
            child: _spaceRow(rooms[i].$1, rooms[i].$2, rooms[i].$3, alert)),
        if (i < rooms.length - 1) const SizedBox(height: 10),
      ],
    ]));
  }

  Widget _spaceRow(String id, String name, IconData icon, SafeHubAlert? alert) {
    final fall = alert != null &&
        alert.kind == AlertKind.fall &&
        alert.data['location'] == id;
    final living = id == 'livingroom';
    final status = fall
        ? '낙상 감지'
        : !_mqttConnected
            ? '연결 확인'
            : living
                ? '수어 번역'
                : '이벤트 대기';
    final subtitle = fall
        ? '즉시 확인이 필요합니다'
        : !_mqttConnected
            ? 'MQTT 연결 끊김'
            : living
                ? '번역 결과 수신 영역'
                : 'Wi-Fi CSI · 센서 상태 미확인';
    final color = fall
        ? const Color(0xFFFF9A93)
        : !_mqttConnected
            ? _amber
            : living
                ? _blue
                : _muted;
    return _glass(
        inset: true,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(children: [
          Icon(icon, size: 29, color: _muted),
          const SizedBox(width: 14),
          _text(name, size: 20, weight: FontWeight.w600),
          const SizedBox(width: 20),
          Expanded(
              child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                _text(status, size: 20, color: color, weight: FontWeight.w600),
                const SizedBox(height: 4),
                _text(subtitle, size: 14, color: _muted),
              ])),
        ]));
  }

  Widget _alarmPanel(SafeHubAlert? alert) {
    final active = alert != null;
    return _glass(
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _heading(Icons.shield_outlined, '경보 시스템'),
      const SizedBox(height: 18),
      Expanded(
          child: _systemRow(Icons.warning_amber_rounded, '화면 경보',
              active ? '알림 발생' : '대기 중', active ? _amber : _green)),
      const Divider(color: Color(0x22FFFFFF), height: 1),
      Expanded(
          child: _systemRow(
              Icons.volume_up_outlined,
              '음성 안내',
              AppConfig.ttsServerUrl.trim().isEmpty ? '미설정' : _ttsStatus,
              _muted)),
      const Divider(color: Color(0x22FFFFFF), height: 1),
      Expanded(
          child:
              _systemRow(Icons.sensors_outlined, '외부 경보 장치', '상태 미연동', _muted)),
      const Divider(color: Color(0x33FFFFFF), height: 1),
      const SizedBox(height: 14),
      Row(children: [
        const Icon(Icons.wifi, color: _blue, size: 25),
        const SizedBox(width: 12),
        Expanded(child: _text('MQTT 브로커', size: 17)),
        _dot(
            _mqttConnected ? '연결됨' : '연결 확인', _mqttConnected ? _green : _amber),
      ]),
      const SizedBox(height: 6),
      _text(AppConfig.mqttBroker + ':' + AppConfig.mqttPort.toString(),
          size: 14, color: _muted),
    ]));
  }

  Widget _systemRow(IconData icon, String label, String value, Color color) =>
      Row(children: [
        Icon(icon, size: 24, color: color),
        const SizedBox(width: 12),
        Expanded(child: _text(label, size: 17)),
        const SizedBox(width: 8),
        Flexible(child: _text(value, color: color, size: 15, lines: 2)),
      ]);

  Widget _disasterPanel() {
    final disaster = _latestDisaster;
    return _glass(
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _heading(Icons.campaign_outlined, '재난 정보',
          trailing: disaster == null
              ? null
              : _more(() => _showDisasterDetails(disaster))),
      const SizedBox(height: 16),
      Expanded(
          child: _glass(
              inset: true,
              padding: const EdgeInsets.all(18),
              child: Row(children: [
                Icon(
                    disaster == null
                        ? Icons.info_outline
                        : _disasterIcon(disaster['DST_SE_NM']?.toString()),
                    size: 34,
                    color: disaster == null
                        ? _muted
                        : _disasterAccent(getDisasterSeverity(disaster))),
                const SizedBox(width: 14),
                Expanded(
                    child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                      _text(
                          disaster == null
                              ? '수신된 정보가 없습니다'
                              : disaster['DST_SE_NM']?.toString() ?? '재난 안내',
                          size: 20,
                          weight: FontWeight.w600,
                          lines: 2),
                      const SizedBox(height: 8),
                      _text(
                          disaster == null
                              ? '재난 API 연결 확인 필요'
                              : disaster['MSG_CN']?.toString() ??
                                  '상세 정보를 확인해 주세요',
                          size: 15,
                          color: _muted,
                          lines: 3),
                    ])),
              ]))),
    ]));
  }

  Widget _more(VoidCallback onTap) => TextButton(
      onPressed: onTap,
      style: TextButton.styleFrom(
          foregroundColor: _muted, minimumSize: const Size(60, 44)),
      child: const Text('더보기 ›', style: TextStyle(fontSize: 15)));

  List<Map<String, dynamic>> get _visibleEvents => _recentEvents
      .where((event) =>
          _selectedRoom == 'all' || event['location'] == _selectedRoom)
      .toList();

  Widget _eventsPanel() {
    final events = _visibleEvents;
    return _glass(
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _heading(Icons.receipt_long_outlined, '최근 이벤트',
          trailing: events.isEmpty ? null : _more(_showEventDetails)),
      const SizedBox(height: 12),
      Expanded(
          child: events.isEmpty
              ? Center(
                  child: _text('아직 수신된 이벤트가 없습니다',
                      size: 17, color: _muted, lines: 2))
              : Column(children: [
                  for (final event in events.take(3))
                    Expanded(child: _eventLine(event)),
                ])),
    ]));
  }

  Widget _eventLine(Map<String, dynamic> event) => Row(children: [
        Icon(Icons.circle,
            size: 8,
            color: _isEmergencyEvent(event) ? const Color(0xFFFF9A93) : _blue),
        const SizedBox(width: 10),
        Expanded(
            child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              _text(_getLocationName(event) + ' · ' + _getEventName(event),
                  size: 17),
              const SizedBox(height: 3),
              _text(_formatEventDateTime(event), size: 14, color: _muted),
            ])),
      ]);

  void _showDisasterDetails(Map<String, dynamic> disaster) => _showDetails(
      '재난 정보',
      [
        disaster['DST_SE_NM']?.toString() ?? '재난 안내',
        disaster['RCPTN_RGN_NM']?.toString() ?? '',
        disaster['CRT_DT']?.toString() ?? '',
        disaster['MSG_CN']?.toString() ?? '내용 없음',
      ].where((s) => s.isNotEmpty).join('\n\n'));

  void _showEventDetails() => _showDetails(
      '최근 이벤트',
      _visibleEvents
          .map((e) =>
              _getLocationName(e) +
              ' · ' +
              _getEventName(e) +
              '\n' +
              _formatEventDateTime(e))
          .join('\n\n'));

  void _showDetails(String title, String body) {
    setState(() {
      _detailTitle = title;
      _detailBody = body;
    });
  }

  Widget _glassTranslation() =>
      Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(
            flex: 4,
            child: _glass(
                child: Column(children: [
              _heading(Icons.sign_language_outlined, '수어 인식'),
              const SizedBox(height: 24),
              Expanded(child: _cameraPlaceholder()),
              const SizedBox(height: 22),
              _dot(_mqttConnected ? 'MQTT 결과 수신 대기' : 'MQTT 연결 확인',
                  _mqttConnected ? _green : _amber),
            ]))),
        const SizedBox(width: 24),
        Expanded(
            flex: 6,
            child: _glass(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                  _heading(Icons.article_outlined, '수어 번역 결과'),
                  const SizedBox(height: 28),
                  Expanded(child: Center(child: _translationText(76))),
                  const Divider(color: Color(0x33FFFFFF)),
                  const SizedBox(height: 20),
                  _systemRow(Icons.volume_up_outlined, '음성 안내', _ttsStatus,
                      _ttsStatus == '음성으로 전달됨' ? _green : _muted),
                  const SizedBox(height: 20),
                ]))),
      ]);

  Widget _buildFallOverlay(Map<String, dynamic> event) {
    final eventName = _getEventName(event);
    final locationName = _getLocationName(event);
    final detectedAt = _formatEventDateTime(event);
    final priority = _getEventPriority(event);
    const accent = Color(0xFFFFA49A);

    // Presentation only: preserve the existing alert acknowledgement lifecycle.
    return Positioned.fill(
      child: BlockSemantics(
        child: Material(
          color: const Color(0xFF24221F),
          child: Stack(
            fit: StackFit.expand,
            children: [
              Image.asset(
                'assets/images/safehub_living_room.png',
                fit: BoxFit.cover,
                errorBuilder: (context, error, stackTrace) =>
                    const ColoredBox(color: Color(0xFF393731)),
              ),
              const DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [Color(0xD923201E), Color(0xC43A2220)],
                  ),
                ),
              ),
              SafeArea(
                child: LayoutBuilder(builder: (context, constraints) {
                  final compact =
                      constraints.maxWidth < 700 || constraints.maxHeight < 650;
                  final padding = compact ? 20.0 : 40.0;
                  return SingleChildScrollView(
                    padding: EdgeInsets.all(padding),
                    child: ConstrainedBox(
                      constraints: BoxConstraints(
                        minHeight:
                            math.max(0.0, constraints.maxHeight - padding * 2),
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Wrap(
                            alignment: WrapAlignment.spaceBetween,
                            spacing: 20,
                            runSpacing: 12,
                            children: [
                              _text('SafeHub',
                                  size: 26, weight: FontWeight.w600),
                              _dot('긴급 안전 알림', accent),
                            ],
                          ),
                          Padding(
                            padding: EdgeInsets.symmetric(
                                vertical: compact ? 24 : 40),
                            child: Center(
                              child: ConstrainedBox(
                                constraints:
                                    const BoxConstraints(maxWidth: 1040),
                                child: AnimatedBuilder(
                                  animation: _alertPulseController,
                                  builder: (context, child) {
                                    final pulse =
                                        MediaQuery.of(context).disableAnimations
                                            ? 0.0
                                            : _alertPulseController.value;
                                    return Container(
                                      decoration: BoxDecoration(
                                        borderRadius: BorderRadius.circular(22),
                                        border: Border.all(
                                          width: 2,
                                          color: Color.lerp(
                                              const Color(0x667F514A),
                                              const Color(0xD9E58A7D),
                                              pulse)!,
                                        ),
                                        boxShadow: [
                                          BoxShadow(
                                            color: Color.fromARGB(
                                                (18 + 20 * pulse).round(),
                                                220,
                                                82,
                                                64),
                                            blurRadius: 30,
                                            spreadRadius: 2,
                                          ),
                                        ],
                                      ),
                                      child: child,
                                    );
                                  },
                                  child: _glass(
                                    padding: EdgeInsets.all(compact ? 24 : 48),
                                    child: Column(
                                      mainAxisSize: MainAxisSize.min,
                                      crossAxisAlignment:
                                          CrossAxisAlignment.stretch,
                                      children: [
                                        const Icon(Icons.warning_amber_rounded,
                                            size: 72, color: accent),
                                        const SizedBox(height: 24),
                                        Semantics(
                                          liveRegion: true,
                                          child: Text(
                                            eventName == '낙상 감지'
                                                ? '낙상이 감지되었습니다'
                                                : eventName,
                                            textAlign: TextAlign.center,
                                            style: TextStyle(
                                              fontFamily: 'Pretendard',
                                              fontSize: compact ? 32 : 50,
                                              height: 1.25,
                                              fontWeight: FontWeight.w600,
                                              color: _ink,
                                              letterSpacing: -1,
                                            ),
                                          ),
                                        ),
                                        const SizedBox(height: 16),
                                        const Text(
                                          '즉시 주변 상황을 확인해 주세요.',
                                          textAlign: TextAlign.center,
                                          style: TextStyle(
                                              color: _muted,
                                              fontSize: 22,
                                              height: 1.4),
                                        ),
                                        const SizedBox(height: 30),
                                        _glass(
                                          inset: true,
                                          child: Column(
                                            children: [
                                              Text(locationName,
                                                  textAlign: TextAlign.center,
                                                  style: const TextStyle(
                                                      color: _ink,
                                                      fontSize: 32,
                                                      fontWeight:
                                                          FontWeight.w600)),
                                              const SizedBox(height: 10),
                                              Text('$detectedAt 감지',
                                                  textAlign: TextAlign.center,
                                                  style: const TextStyle(
                                                      color: _muted,
                                                      fontSize: 18)),
                                              const SizedBox(height: 10),
                                              Text('긴급도 $priority / 10',
                                                  style: const TextStyle(
                                                      color: accent,
                                                      fontSize: 18,
                                                      fontWeight:
                                                          FontWeight.w600)),
                                            ],
                                          ),
                                        ),
                                        const SizedBox(height: 30),
                                        Center(
                                          child: ConstrainedBox(
                                            constraints: const BoxConstraints(
                                                maxWidth: 400),
                                            child: SizedBox(
                                              width: double.infinity,
                                              child: FilledButton.icon(
                                                onPressed:
                                                    _acknowledgeActiveAlert,
                                                icon: const Icon(
                                                    Icons.check_rounded),
                                                label: const Text('경보 확인'),
                                                style: FilledButton.styleFrom(
                                                  backgroundColor:
                                                      const Color(0xFFAD443B),
                                                  foregroundColor: Colors.white,
                                                  minimumSize:
                                                      const Size(0, 64),
                                                  padding:
                                                      const EdgeInsets.all(18),
                                                  textStyle: const TextStyle(
                                                      fontFamily: 'Pretendard',
                                                      fontSize: 22,
                                                      fontWeight:
                                                          FontWeight.w600),
                                                  shape: RoundedRectangleBorder(
                                                      borderRadius:
                                                          BorderRadius.circular(
                                                              14)),
                                                ),
                                              ),
                                            ),
                                          ),
                                        ),
                                        const SizedBox(height: 14),
                                        const Text(
                                          '경보 확인은 안전 확인 완료를 의미하지 않습니다.',
                                          textAlign: TextAlign.center,
                                          style: TextStyle(
                                              color: _muted,
                                              fontSize: 15,
                                              height: 1.4),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                          const Text('SafeHub · 공간 안전 모니터링',
                              textAlign: TextAlign.center,
                              style: TextStyle(color: _muted, fontSize: 15)),
                        ],
                      ),
                    ),
                  );
                }),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _getEventName(Map<String, dynamic> event) {
    switch (event['event']) {
      case 'fall_detected':
        return '낙상 감지';
      default:
        return event['event']?.toString() ?? '안전 이벤트';
    }
  }

  String _getLocationName(Map<String, dynamic> event) {
    switch (event['location']) {
      case 'bedroom':
        return '침실';
      case 'bathroom':
        return '화장실';
      default:
        return '실내';
    }
  }

  String _formatEventDateTime(Map<String, dynamic> event) {
    final raw = event['_receivedAt']?.toString();

    if (raw == null || raw.isEmpty) {
      return '감지 시각 확인 불가';
    }

    final parsed = DateTime.tryParse(raw);

    if (parsed == null) {
      return '감지 시각 확인 불가';
    }

    final local = parsed.toLocal();
    final year = local.year.toString().padLeft(4, '0');
    final month = local.month.toString().padLeft(2, '0');
    final day = local.day.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');

    return '$year/$month/$day $hour:$minute';
  }

  Color _disasterAccent(DisasterSeverity severity) {
    switch (severity) {
      case DisasterSeverity.notice:
        return const Color(0xFFF59E0B);
      case DisasterSeverity.emergency:
        return const Color(0xFFEA580C);
      case DisasterSeverity.critical:
        return const Color(0xFFDC2626);
    }
  }

  IconData _disasterIcon(String? type) {
    switch (type) {
      case '폭염':
        return Icons.sunny;
      case '호우':
        return Icons.water_drop_outlined;
      case '태풍':
        return Icons.cyclone;
      case '대설':
        return Icons.ac_unit;
      case '산불':
        return Icons.local_fire_department_outlined;
      case '지진':
        return Icons.vibration;
      case '미세먼지':
        return Icons.air;
      default:
        return Icons.campaign_outlined;
    }
  }
}

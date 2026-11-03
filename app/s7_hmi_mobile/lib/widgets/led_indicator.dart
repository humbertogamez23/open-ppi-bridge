import 'package:flutter/material.dart';

class LedIndicator extends StatelessWidget {
  final String label;
  final bool active;
  final Color activeColor;

  const LedIndicator({
    super.key,
    required this.label,
    required this.active,
    this.activeColor = const Color(0xFF00E676), // Verde brillante
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          width: 24,
          height: 24,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: active ? activeColor : const Color(0xFF263238),
            border: Border.all(
              color: active ? activeColor.withValues(alpha: 0.8) : const Color(0xFF455A64),
              width: 1.5,
            ),
            boxShadow: active
                ? [
                    BoxShadow(
                      color: activeColor.withValues(alpha: 0.6),
                      blurRadius: 10,
                      spreadRadius: 2,
                    )
                  ]
                : [],
          ),
          child: Center(
            child: Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: active ? Colors.white.withValues(alpha: 0.8) : Colors.transparent,
              ),
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(
            color: active ? Colors.white : const Color(0xFF90A4AE),
            fontSize: 10,
            fontWeight: active ? FontWeight.bold : FontWeight.normal,
            fontFamily: 'monospace',
          ),
        ),
      ],
    );
  }
}

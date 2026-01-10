using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace SampleGame
{
    public class GameManager : MonoBehaviour
    {
        private List<Enemy> _enemies;
        private float _damageInterval = 1.0f; // 1秒ごと
        private float _lastDamageTime;

        private void Update()
        {
            if (Time.time - _lastDamageTime >= _damageInterval)
            {
                ProcessFirstEnemy();
                _lastDamageTime = Time.time;
            }
        }

        private void ProcessFirstEnemy()
        {
            if (_enemies == null || _enemies.Count == 0) return;
            var first = _enemies[0];
            first.TakeDamage(10);
        }

        public string LoadData()
        {
            using (var reader = new StreamReader("data.txt"))
            {
                return reader.ReadToEnd();
            }
        }
    }
}

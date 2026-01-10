using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace SampleGame
{
    public class GameManager : MonoBehaviour
    {
        private List<Enemy> _enemies = new List<Enemy>();

        private void Update()
        {
            ProcessFirstEnemy();
        }

        private void ProcessFirstEnemy()
        {
            if (_enemies == null || _enemies.Count == 0)
            {
                return;
            }
            var first = _enemies[0];
            first.TakeDamage(10);
        }

        public string LoadData()
        {
            var filePath = "data.txt";
            if (!File.Exists(filePath))
            {
                Debug.LogWarning($"File not found: {filePath}");
                return string.Empty;
            }
            using (var reader = new StreamReader(filePath))
            {
                return reader.ReadToEnd();
            }
        }
    }

    public class Enemy
    {
        public void TakeDamage(int damage) { }
    }
}

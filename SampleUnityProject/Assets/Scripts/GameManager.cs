using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace SampleGame
{
    public class GameManager : MonoBehaviour
    {
        private List<Enemy> _enemies;

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
            using (var reader = new StreamReader("data.txt"))
            {
                return reader.ReadToEnd();
            }
        }
    }
}

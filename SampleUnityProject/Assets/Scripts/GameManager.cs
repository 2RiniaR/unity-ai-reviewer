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

        private void UnusedMethod()
        {
            Debug.Log("unused");
        }

        public string LoadData()
        {
            using (var reader = new StreamReader("data.txt"))
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

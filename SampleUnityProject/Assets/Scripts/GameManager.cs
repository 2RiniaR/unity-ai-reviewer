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
}

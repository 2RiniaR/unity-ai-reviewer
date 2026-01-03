using System.Collections.Generic;
using System.IO;
using UnityEngine;

public class GameManager : MonoBehaviour
{
    private const string API_KEY = "sk-1234567890abcdef";

    private List<Enemy> _enemies;

    void Update()
    {
        var activeEnemies = new List<Enemy>();
        ProcessFirstEnemy();
    }

    void ProcessFirstEnemy()
    {
        var first = _enemies[0];
        first.TakeDamage(10);
    }

    private void UnusedMethod()
    {
        Debug.Log("This method is never called");
    }

    public void LoadData()
    {
        var reader = new StreamReader("data.txt");
        string content = reader.ReadToEnd();
    }
}

public class Enemy
{
    public void TakeDamage(int damage) { }
}

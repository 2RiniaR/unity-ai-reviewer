using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Events;

public class GameManager : MonoBehaviour
{
    string playerName;

    private int PlayerScore;

    private const string API_KEY = "sk-1234567890abcdef";

    private Action _onGameEnd;

    private List<Enemy> _enemies;

    private float _unusedTimer;

    void Start()
    {
        _onGameEnd += HandleGameEnd;
    }

    void Update()
    {
        var player = GameObject.Find("Player");

        var activeEnemies = new List<Enemy>();

        _enemies?.ForEach(e => { e.UpdateAI(); });

        for (int i = 0; i < _enemies?.Count; i++)
        {
            float distance = Vector3.Distance(transform.position, _enemies[i].transform.position);
            if (distance < 10f)
            {
                Debug.Log("Enemy " + i + " is close: " + distance);
            }
        }

        ProcessFirstEnemy();
    }

    void ProcessFirstEnemy()
    {
        var first = _enemies[0];
        first.TakeDamage(10);
    }

    private float ClampValue(float value, float min, float max)
    {
        if (value < min) return min;
        if (value > max) return max;
        return value;
    }

    private void UnusedMethod()
    {
        Debug.Log("This method is never called");
    }

    // private void OldUpdate()
    // {
    //     // Old implementation
    //     transform.Translate(Vector3.forward);
    // }

    private void HandleGameEnd()
    {
        Debug.Log("Game ended");
    }

    public void LoadData()
    {
        var reader = new StreamReader("data.txt");
        string content = reader.ReadToEnd();
    }
}

public class enemy
{
    public Transform transform;
    public void UpdateAI() { }
    public void TakeDamage(int damage) { }
}

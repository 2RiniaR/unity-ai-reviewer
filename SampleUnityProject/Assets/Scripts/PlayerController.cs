using System.Collections.Generic;
using UnityEngine;

public class PlayerController : MonoBehaviour
{
    private List<Item> _items;

    void Update()
    {
        ProcessFirstItem();
    }

    void ProcessFirstItem()
    {
        var first = _items[0];
        first.Use();
    }

    public void OnMove(Vector3 direction)
    {
        transform.Translate(direction * Time.deltaTime);
    }
}

public class Item
{
    public void Use() { }
}

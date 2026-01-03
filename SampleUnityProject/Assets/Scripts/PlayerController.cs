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
}

public class Item
{
    public void Use() { }
}

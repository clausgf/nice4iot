NiceModel
=========

NiceModel tries to simplify [NiceGUI](https://nicegui.io) programming by deriving forms and tables from Pydantic models. Inspiration was gatherd from
- [MagicGUI](https://magicgui.readthedocs.io/)
- [NiceCRUD](https://github.com/zauberzeug/nicegui/tree/main/examples/nicecrud)
- ... and the great [Django](https://docs.djangoproject.com/) ORM integration

NiceModel is intended as an adapter layer between NiceGUI elements (widgets) and your application. Based on a pydantic model of your data, the adapters configure the elements. This is used to create forms and tables.

TODO
----
- life cycle is not clear. when are nicegui elements instantiated, when active, when deleted?
- when is the polling implementation of binding active? problem?
- support binding in tables?
- support validation: use pydantic validators for validation & render nice error messages - is Quasar's QForm somehow helpful?
- when shall we save data? does an apply button make sense? make this button active?

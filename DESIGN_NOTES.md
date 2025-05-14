# Random Nice4iot design notes

## Pydantic-Forms
Ansätze:
- MagicGUI
- NiceCRUD

Field(title="Name", description="Your name", default="John Doe", max_length=30)

### Dango ORM
Wie kann man den Ideen aus Django ORM in das Pydantic Model übernehmen, um bei der UI-Generierung zu helfen?

Properties von Django Model Fields:
- *required*, blank, null
- choices? (Thema für sich)
- default
- editable
- error_messages (dict, keys=null, blank, invalid, invalid_choice, unique, unique_for_date, ...)
- help_text="Hilfetext, z.B. für Tooltip"
- unique=False
- unique_for_date="name_of_date_field"
- unique_for_month="name_of_date_field"
- unique_for_year="name_of_date_field"
- verbose_name: A human-readable name for the field. If the verbose name isn’t given, Django will automatically create it using the field’s attribute name, converting underscores to spaces.
- validators: A list of validators to run for this field.


- auch formfield(form_class=None, choices_form_class=None, **kwargs)
- DB: primary_key, db_column, ...


ToDo
- DateTime Handling inkl. TZ? -> Time, Date, DateTime
- Relationships
- class Meta in der Modellklasse mit verbose_name, verbose_name_plural, ordering


### Python typing
Add metadata x to type T: Annotated[T, x]
If a library or tool encounters an annotation Annotated[T, x] and has no special logic for the metadata, it should ignore the metadata and simply treat the annotation as T. As such, Annotated can be useful for code that wants to use annotations for purposes outside Python’s static typing system.

```python
@dataclass
class ValueRange:
    lo: int
    hi: int

T1 = Annotated[int, ValueRange(-10, 5)]
T2 = Annotated[T1, ValueRange(-20, 3)]
```

By default, get_type_hints() strips the metadata from annotations. Pass include_extras=True to have the metadata preserved.

At runtime, the metadata associated with an Annotated type can be retrieved via the __metadata__ attribute:

```python
from typing import Annotated
X = Annotated[int, "very", "important", "metadata"]
X

X.__metadata__
```

If you want to retrieve the original type wrapped by Annotated, use the __origin__ attribute:

```python
from typing import Annotated, get_origin
Password = Annotated[str, "secret"]
Password.__origin__
```

### Pydantic Field function

```python
class Model(BaseModel):
    name: Annotated[str, Field(strict=True), WithJsonSchema({'extra': 'data'})]

class Foo(BaseModel):
    positive: int = Field(gt=0)
    non_negative: int = Field(ge=0)
    even: int = Field(multiple_of=2)
    short: str = Field(min_length=3)
    long: str = Field(max_length=10)
    regex: str = Field(pattern=r'^\d*$')  
    precise: Decimal = Field(max_digits=5, decimal_places=2)

class User(BaseModel):
    age: int = Field(description='Age of the user')
    email: EmailStr = Field(examples=['marcelo@mail.com'])
    name: str = Field(title='Username')
    password: SecretStr = Field(
        json_schema_extra={
            'title': 'Password',
            'description': 'Password of the user',
            'examples': ['123456'],
        }
    )

- Versteht Field() beliebige kwopts, oder müssen wir auf json_schema_extra= gehen? NiceCRUD mach das so, ist aber sehr unschön

```

```python
```

```python
```

